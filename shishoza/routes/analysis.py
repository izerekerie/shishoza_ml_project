"""Parcel input, risk analysis, cut simulation, guidance, and the USSD gateway."""

from __future__ import annotations

import datetime
import json
import sqlite3
import sys
from concurrent.futures import TimeoutError as _EETimeout
from pathlib import Path

from flask import Blueprint, Response, jsonify, request

from ..config import (CLEARED_NDVI, DB_PATH, EE_POOL, LIVE_CACHE_TTL_S,
                      LIVE_EE_TIMEOUT_S, NOW_END, NOW_START, ROOT,
                      SECTORS_GEOJSON, UPLOAD_DIR)
from ..auth import current_user, login_required
from ..db import recall_analysis, remember_analysis
from ..model import (analyse_parcel, analyse_parcel_live, ensure_ee, _subrisks,
                     sector_for_point, _SECTORS)
from ..monitoring import log_prediction

# The cadastral extractor lives in scripts/, imported the same way the monolith
# did (path insert + top-level module import).
sys.path.insert(0, str(ROOT / "scripts"))
from extract_cadastral import extract  # type: ignore  # noqa: E402

bp = Blueprint("analysis", __name__)


@bp.post("/api/analyse-sector")
@login_required
def api_analyse_sector():
    """Run the full Shishoza model on an arbitrary sector — used when the Forest
    Manager clicks a sector on the choropleth. Same pipeline as the citizen flow,
    just keyed by sector_id instead of GPS/draw/upload."""
    data = request.get_json() or {}
    sector_id = (data.get("sector_id") or "").strip()
    if not sector_id:
        return jsonify({"error": "sector_id required"}), 400
    row = _SECTORS[_SECTORS["sector_id"].astype(str) == sector_id]
    if row.empty:
        return jsonify({"error": f"Unknown sector_id {sector_id}"}), 404
    sec = row.iloc[0]

    # Enforce district scope so managers can't analyse outside their patch
    user = current_user()
    if user["district_scope"] and sec["district"] != user["district_scope"]:
        return jsonify({"error": "Sector outside your district scope"}), 403

    result = analyse_parcel(
        lat=float(sec["centroid_lat"]),
        lng=float(sec["centroid_lng"]),
        area_ha=None,
    )
    result["sector_id"]   = sector_id
    result["sector_name"] = str(sec["sector"])
    result["district"]    = str(sec["district"])
    result["province"]    = str(sec["province"])
    result["centroid_lat"] = float(sec["centroid_lat"])
    result["centroid_lng"] = float(sec["centroid_lng"])
    return jsonify(result)


@bp.get("/api/sector-risk")
@login_required
def api_sector_risk():
    """Sector-level risk data scoped to the logged-in user's district.
    Admins see every sector; forest managers see only their assigned district.
    ---
    tags:
      - Guidance
    produces:
      - application/json
    responses:
      200:
        description: Per-sector aggregated risk scores, scoped to the caller's district.
      401:
        description: Authentication required.
      500:
        description: sector_risk.json has not been generated yet.
    """
    path = ROOT / "results" / "application" / "sector_risk.json"
    if not path.exists():
        return jsonify({"error": "sector_risk.json not generated yet"}), 500
    data = json.loads(path.read_text())
    user = current_user()
    scope = user.get("district_scope")
    if scope:  # forest manager — keep only sectors in their district
        in_scope = [s for s in data["sectors"] if s["district"] == scope]
        risks = [s["risk_level"] for s in in_scope]
        data["sectors"] = in_scope
        data["summary"] = {
            "total_sectors":       len(in_scope),
            "assessed_sectors":    sum(1 for r in risks if r != "UNKNOWN"),
            "high_risk_sectors":   risks.count("HIGH"),
            "medium_risk_sectors": risks.count("MEDIUM"),
            "low_risk_sectors":    risks.count("LOW"),
        }
        data["scope"] = {"district": scope, "view": "district_only"}
    else:  # admin — pass through
        data["scope"] = {"district": "ALL", "view": "national"}
    data["user"] = {
        "full_name":      user["full_name"],
        "role":           user["role"],
        "district_scope": user["district_scope"],
    }
    return jsonify(data)


@bp.get("/static/sectors.geojson")
def sectors_geojson():
    """Serve the bundled sector polygons (cached aggressively in the browser)."""
    return SECTORS_GEOJSON.read_text(), 200, {
        "Content-Type": "application/json",
        "Cache-Control": "public, max-age=86400",
    }


@bp.get("/api/districts")
def api_districts():
    """Sorted unique district names, for routing a review request.
    ---
    tags: [Review workflow]
    responses:
      200: {description: "Sorted list of district names for routing a review request."}
    """
    try:
        ds = sorted(str(d) for d in _SECTORS["district"].dropna().unique())
    except Exception:
        ds = []
    return jsonify({"districts": ds})


@bp.post("/api/alternatives")
def api_alternatives():
    """Return vetted alternatives for a given cutting reason.
    Triggered when the citizen selects a cutting reason; returns pre-written,
    source-verified suggestions (e.g. government programs) for that reason,
    independent of risk level, in the requested language (falling back to
    English when a translation is not yet available).
    ---
    tags:
      - Guidance
    consumes:
      - application/json
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [analysis_id, reason]
          properties:
            analysis_id:
              type: integer
              description: ID returned by a prior /api/analyse call.
              example: 1
            reason:
              type: string
              enum: [firewood, timber, farming, income]
              description: Why the citizen wants to cut.
              example: firewood
            language:
              type: string
              enum: [rw, en, fr]
              default: en
              description: Language for the suggestion text.
    responses:
      200:
        description: Matching suggestions for (reason, risk_level, language).
      400:
        description: analysis_id and reason required; reason must be a valid enum value.
    """
    data = request.get_json() or {}
    try:
        aid    = int(data["analysis_id"])
        reason = str(data["reason"]).lower()
    except (KeyError, ValueError, TypeError):
        return jsonify({"error": "analysis_id and reason required"}), 400
    if reason not in ("firewood", "timber", "farming", "income"):
        return jsonify({"error": "reason must be firewood, timber, farming, or income"}), 400
    language = data.get("language", "en")

    orig = recall_analysis(aid)
    risk_level = orig["risk_level"] if orig else "HIGH"

    if not DB_PATH.exists():
        return jsonify({"suggestions": [], "warning": "DB not initialised"})

    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row

    # Suggestions are keyed to the cutting REASON, not the parcel's risk level.
    # Pull all risk levels for the reason, order the most cautionary (HIGH) first,
    # and fall back to English when the requested language has no rows yet.
    def _lookup(lang):
        return con.execute(
            "SELECT suggestion_text, gov_program_url, source_verified, risk_level "
            "FROM ALTERNATIVES WHERE reason = ? AND language = ? "
            "ORDER BY CASE risk_level WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END",
            (reason, lang)
        ).fetchall()

    rows = _lookup(language)
    used_language = language
    if not rows and language != "en":
        rows = _lookup("en")
        used_language = "en"
    con.close()

    # De-duplicate by suggestion text, keeping the first (highest-risk) copy.
    seen, suggestions = set(), []
    for r in rows:
        if r["suggestion_text"] in seen:
            continue
        seen.add(r["suggestion_text"])
        suggestions.append({
            "suggestion_text": r["suggestion_text"],
            "gov_program_url": r["gov_program_url"],
            "source_verified": r["source_verified"],
        })

    return jsonify({
        "analysis_id":  aid,
        "reason":       reason,
        "risk_level":   risk_level,
        "language":     used_language,
        "suggestions":  suggestions,
    })


@bp.post("/api/simulate")
def api_simulate():
    """Forward-simulate a proposed cut on an already-analysed parcel.
    Estimates the parcel's NDVI, tree cover and neighbourhood state after
    clearing `cut_area_ha`, then re-runs the three-rule risk classifier.

    Math:  new_ndvi  = (1 - f) * orig_ndvi + f * CLEARED_NDVI
           where f = cut_area_ha / parcel_area_ha
           new_neigh_deforested_pct += (cut_area_ha / 78.5) * 100
    ---
    tags:
      - Risk analysis
    consumes:
      - application/json
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [analysis_id, cut_area_ha]
          properties:
            analysis_id:
              type: integer
              description: ID returned by a prior /api/analyse call.
              example: 1
            cut_area_ha:
              type: number
              description: Proposed clearing area in hectares (0 < cut ≤ parcel area).
              example: 0.02
    responses:
      200:
        description: Before / after / delta of the simulated cut.
      400:
        description: Missing fields, or cut_area_ha outside (0, parcel_area].
      404:
        description: analysis_id not found — run /api/analyse first.
    """
    data = request.get_json() or {}
    try:
        aid = int(data["analysis_id"])
        cut = float(data["cut_area_ha"])
    except (KeyError, ValueError, TypeError):
        return jsonify({"error": "analysis_id and cut_area_ha required"}), 400

    orig = recall_analysis(aid)
    if orig is None:
        return jsonify({"error": "analysis_id not found — run /api/analyse first"}), 404
    parcel_area = orig.get("parcel_area_ha") or 0.05
    if cut <= 0 or cut > parcel_area:
        return jsonify({"error": f"cut_area_ha must be in (0, {parcel_area}]"}), 400

    f = cut / parcel_area
    new_ndvi  = (1 - f) * orig["ndvi_current"] + f * CLEARED_NDVI
    new_tree_cover = max(0.0, min(100.0, new_ndvi * 100.0))
    new_neigh_def  = orig["neighbourhood_500m_deforested_pct"] + (cut / 78.5) * 100

    # Re-run the 3-rule classifier on the simulated state
    prob = orig["deforestation_prob"]   # keep model prob; cut affects context not pixel-level
    avg_ndvi_500m = orig["neighbourhood_500m_avg_ndvi"]
    rule1 = (prob > 0.65) or (new_tree_cover < 30)
    rule2 = (new_neigh_def > 50) and (new_ndvi < avg_ndvi_500m * 0.70)
    rule3 = (0.35 < prob <= 0.65) and (new_neigh_def > 0)
    if rule1 or rule2:
        new_risk = "HIGH"
        fired   = "Rule 1 (parcel)" if rule1 else "Rule 2 (neighbourhood)"
    elif rule3:
        new_risk = "MEDIUM"; fired = "Rule 3"
    else:
        new_risk = "LOW";    fired = "default"

    risk_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    delta_risk = risk_order[new_risk] - risk_order[orig["risk_level"]]

    before_parcel, before_nbr = _subrisks(prob, orig["tree_cover_pct"], orig["neighbourhood_500m_deforested_pct"])
    after_parcel,  after_nbr  = _subrisks(prob, new_tree_cover, new_neigh_def)

    return jsonify({
        "before": {
            "risk_level":            orig["risk_level"],
            "parcel_risk":           before_parcel,
            "neighbourhood_risk":    before_nbr,
            "tree_cover_pct":        orig["tree_cover_pct"],
            "ndvi_current":          orig["ndvi_current"],
            "neighbourhood_500m_deforested_pct": orig["neighbourhood_500m_deforested_pct"],
        },
        "after": {
            "risk_level":            new_risk,
            "parcel_risk":           after_parcel,
            "neighbourhood_risk":    after_nbr,
            "tree_cover_pct":        round(new_tree_cover, 1),
            "ndvi_current":          round(new_ndvi, 3),
            "neighbourhood_500m_deforested_pct": round(new_neigh_def, 1),
            "rule_fired":            fired,
        },
        "delta": {
            "tree_cover_pct":        round(new_tree_cover - orig["tree_cover_pct"], 1),
            "ndvi_current":          round(new_ndvi - orig["ndvi_current"], 3),
            "neighbourhood_500m_deforested_pct": round(new_neigh_def - orig["neighbourhood_500m_deforested_pct"], 1),
            "risk_level_change":     delta_risk,   # +1 means risk worsened by one class
        },
        "recovery_years_estimate": "6–8 years",   # from Hansen 2020-22 → 2024 recovery trend
        "cleared_ndvi_reference":  round(CLEARED_NDVI, 3),
        "cut_fraction":            round(f, 3),
    })


@bp.post("/api/analyse")
def api_analyse():
    """Assess deforestation risk for a parcel at a given location.
    Looks up the nearest trained pixel, runs the tuned Random Forest, applies
    the three-rule risk classifier, and returns the parcel + neighbourhood state.
    The returned analysis_id can then be passed to /api/simulate and /api/alternatives.
    ---
    tags:
      - Risk analysis
    consumes:
      - application/json
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [lat, lng]
          properties:
            lat:
              type: number
              description: Latitude (WGS84).
              example: -2.4521
            lng:
              type: number
              description: Longitude (WGS84).
              example: 29.1043
            area_ha:
              type: number
              description: Optional parcel area in hectares.
              example: 0.05
    responses:
      200:
        description: Risk assessment for the parcel.
      400:
        description: lat and lng are required and must be floats.
    """
    data = request.get_json() or {}
    try:
        lat = float(data["lat"])
        lng = float(data["lng"])
    except (KeyError, ValueError, TypeError):
        return jsonify({"error": "lat and lng are required floats"}), 400
    area_ha = data.get("area_ha")
    # Lazy geo-cache: analysis_id is a deterministic hash of the rounded location,
    # so a prior LIVE pull for this exact parcel is already stored under it.
    aid = abs(hash((round(lat, 5), round(lng, 5)))) % 10_000_000
    cached = recall_analysis(aid)
    if (cached
            and cached.get("data_source") == "live_gee"
            and round(cached.get("lat", 1e9), 5) == round(lat, 5)
            and round(cached.get("lng", 1e9), 5) == round(lng, 5)
            and (datetime.datetime.now().timestamp() - cached.get("cached_at", 0)) < LIVE_CACHE_TTL_S):
        out = dict(cached)
        out["cache_hit"] = True
        log_prediction(lat, lng, out)
        return jsonify(out)
    # Prefer LIVE Earth Engine imagery for the exact parcel; fall back to the
    # nearest-sample path if EE is unavailable or the live pull fails.
    result = None
    if ensure_ee():
        try:
            result = EE_POOL.submit(analyse_parcel_live, lat, lng, area_ha).result(
                timeout=LIVE_EE_TIMEOUT_S)
        except _EETimeout:
            print(f"[warn] live EE pull exceeded {LIVE_EE_TIMEOUT_S}s — using fast local fallback")
        except Exception as e:
            print(f"[warn] live parcel analysis failed, falling back ({e})")
    if result is None:
        result = analyse_parcel(lat, lng, area_ha=area_ha)
    # Stamp live pulls so the geo-cache above can age them out; the fast fallback is
    # left unstamped so it is never cached in place of a real live reading.
    if result.get("data_source") == "live_gee":
        result["cached_at"] = datetime.datetime.now().timestamp()
    # Attach the containing sector/district so a cutting-permission request can be
    # routed to the right district manager (and pre-fill the citizen's dropdown).
    _sec = sector_for_point(result.get("lat"), result.get("lng"))
    if _sec:
        result.setdefault("sector_id", _sec["sector_id"])
        result.setdefault("sector_name", _sec["sector"])
        result.setdefault("district", _sec["district"])
    # Persist so /api/simulate and /api/alternatives can reference it from ANY
    # gunicorn worker, not just the one that ran this request.
    remember_analysis(result)
    log_prediction(lat, lng, result)   # production usage + drift log
    return jsonify(result)


@bp.post("/api/manual-coords")
def api_manual_coords():
    """Manual coordinate entry — citizen reads the printed numbers from
    their certificate and types them in. Same output shape as /api/extract
    so the rest of the front-end pipeline doesn't care which path was used.
    ---
    tags:
      - Parcel input
    consumes:
      - application/json
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [easting, northing]
          properties:
            easting:
              type: number
              description: Rwanda local TM easting (500,000–600,000).
              example: 530412
            northing:
              type: number
              description: Rwanda local TM northing (4,700,000–4,900,000).
              example: 4793215
            area_sqm:
              type: number
              description: Optional parcel area in m²; if given, a square polygon is drawn.
              example: 512
    responses:
      200:
        description: Coordinates converted to WGS84 lat/lng (+ optional polygon).
      400:
        description: Missing/invalid numbers, or coordinates outside Rwanda's range.
    """
    from pyproj import Transformer
    transformer = Transformer.from_crs(
        "+proj=tmerc +lat_0=0 +lon_0=30 +k=0.9999 +x_0=500000 +y_0=5000000 "
        "+ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs",
        "EPSG:4326", always_xy=True
    )
    data = request.get_json() or {}
    try:
        easting  = float(data["easting"])
        northing = float(data["northing"])
    except (KeyError, ValueError, TypeError):
        return jsonify({"error": "Easting and Northing required as numbers"}), 400
    area_sqm = data.get("area_sqm")

    # Basic sanity: Rwanda local TM Easting is 5xx,xxx; Northing 47xx,xxx-48xx,xxx
    if not (500_000 <= easting <= 600_000):
        return jsonify({"error": f"Easting {easting} outside Rwanda's UTM range (500-600k)"}), 400
    if not (4_700_000 <= northing <= 4_900_000):
        return jsonify({"error": f"Northing {northing} outside Rwanda's UTM range"}), 400

    lng, lat = transformer.transform(easting, northing)

    # If the citizen provided an area, build an approximate square polygon for display
    polygon_wgs84 = None
    if area_sqm and area_sqm > 0:
        side_m = (float(area_sqm)) ** 0.5
        half = side_m / 2
        corners_utm = [
            (easting - half, northing + half),  # TL
            (easting + half, northing + half),  # TR
            (easting + half, northing - half),  # BR
            (easting - half, northing - half),  # BL
        ]
        polygon_wgs84 = []
        for e, n in corners_utm:
            cx, cy = transformer.transform(e, n)
            polygon_wgs84.append([cx, cy])
        polygon_wgs84.append(polygon_wgs84[0])

    return jsonify({
        "upi": None,
        "surface_sqm": area_sqm,
        "easting": easting,
        "northing": northing,
        "lat": lat,
        "lng": lng,
        "polygon_wgs84": polygon_wgs84,
        "extracted_area_m2": area_sqm,
        "polygon_status": "manual" if polygon_wgs84 else "manual_centroid_only",
        "source": "manual_entry",
    })


@bp.post("/api/extract")
def api_extract():
    """Extract a parcel location from an uploaded land-title document.
    Runs OCR + cadastral parsing on a Rwanda land title (PDF or photo) and
    returns the parcel centroid, polygon, and UPI where detectable.
    ---
    tags:
      - Parcel input
    consumes:
      - multipart/form-data
    parameters:
      - name: file
        in: formData
        type: file
        required: true
        description: A land-title PDF or photo (.pdf, .png, .jpg, .jpeg, .webp, .tiff). Max 16 MB.
    responses:
      200:
        description: Extracted parcel location and geometry.
      400:
        description: No file uploaded, or unsupported file type.
      500:
        description: Extraction failed (OCR or parsing error).
    """
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No file uploaded"}), 400

    suffix = "." + f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
    if suffix not in {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tiff"}:
        return jsonify({"error": f"Unsupported file type: {suffix}"}), 400

    # Write to a project-local temp file (sandbox rules block /tmp tesseract reads)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    tmp = UPLOAD_DIR / f"upload_{abs(hash(f.filename))}{suffix}"
    try:
        f.save(tmp)
        result = extract(tmp)
    except Exception as e:
        return jsonify({"error": f"Extraction failed: {e}"}), 500
    finally:
        if tmp.exists():
            tmp.unlink()

    return jsonify(result)


# ── USSD gateway (Africa's Talking sandbox / future live deployment) ────────
# Africa's Talking sends a POST with: sessionId, serviceCode, phoneNumber, text.
# Responses: "CON <msg>" = keep session open, "END <msg>" = close session.
@bp.post("/ussd")
def ussd_gateway():
    text = request.form.get("text", "").strip()

    # text is empty on first dial, then accumulates inputs separated by *
    steps = [s.strip() for s in text.split("*")] if text else []

    if not steps or steps == [""]:
        # First interaction — welcome screen
        return _ussd("CON",
            "Shishoza\n"
            "Deforestation risk checker\n"
            "--------------------------------\n"
            "Enter your UPI number:\n"
            "(e.g. 1/01/03/05/4924)")

    upi = steps[0].upper().strip()

    # Look up the most recent cached analysis for this UPI
    result = None
    if DB_PATH.exists():
        try:
            con = sqlite3.connect(str(DB_PATH), timeout=5)
            con.row_factory = sqlite3.Row
            row = con.execute(
                "SELECT payload FROM ANALYSIS_CACHE "
                "WHERE json_extract(payload, '$.upi') = ? "
                "ORDER BY analysis_id DESC LIMIT 1",
                (upi,)
            ).fetchone()
            con.close()
            if row:
                result = json.loads(row["payload"])
        except Exception:
            pass

    if result is None:
        return _ussd("END",
            f"UPI {upi} has not been analysed yet.\n\n"
            "Visit the Shishoza web app to\n"
            "analyse your parcel first, then\n"
            "dial again for the USSD summary.")

    risk    = result.get("risk_level", "UNKNOWN")
    prob    = result.get("deforestation_prob", 0)
    cover   = result.get("tree_cover_pct", 0)
    ndvi_t  = result.get("ndvi_2020", 0)
    ndvi_c  = result.get("ndvi_current", 0)
    trend   = "recovering" if ndvi_c > ndvi_t else ("declining" if ndvi_c < ndvi_t else "stable")

    risk_rw = {"HIGH": "INKURIKIZI IKABIJE", "MEDIUM": "INKURIKIZI HAGATI", "LOW": "INKURIKIZI NKEYA"}.get(risk, risk)

    return _ussd("END",
        f"UPI: {upi}\n"
        f"Risk: {risk} ({prob:.0%})\n"
        f"Tree cover: {cover:.0f}%\n"
        f"Forest: {trend}\n"
        f"({risk_rw})\n\n"
        "Full report: visit Shishoza web app")


def _ussd(action, message):
    """Return a plain-text USSD response (Africa's Talking format)."""
    return Response(f"{action} {message}", mimetype="text/plain")
