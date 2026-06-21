#!/usr/bin/env python3
"""
Extract location data from a Rwanda land-title cadastral plan.

Handles both:
  - Digital PDFs (selectable text) — fast path via pdfplumber
  - Photos / scanned images — needs OCR (Tesseract or Claude vision)

Returns a JSON-serialisable dict:
  {
    "upi":          "5/01/10/05/7914",
    "surface_sqm":  383,
    "easting":      527187,
    "northing":     4781470,
    "lat":          -1.9...,
    "lng":          30.0...,
    "province":     "Eastern",
    "district":     "Rwamagana",
    "sector":       "MUYUMBU",
    "cell":         "NYARUKOMBE",
    "village":      "Gituza",
    "source":       "pdf_text"     # or "ocr"
  }

Usage:
  python scripts/extract_cadastral.py path/to/cert.pdf
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


# ── Rwanda's official cadastral projection
#    Custom Transverse Mercator on ITRF 2005 datum (GRS80 ellipsoid):
#       central meridian  = 30°E
#       false easting     = 500,000
#       false northing    = 5,000,000      ← NOT standard UTM-35S (10,000,000)
#       scale factor      = 0.9999
#    This is the CRS that appears in the village_boundary GeoJSON and on the
#    cadastral plan grid labels. WGS84 ↔ ITRF 2005 differ by <1 m — negligible
#    when we're picking 10 m Sentinel-2 pixels.
from pyproj import Transformer

_RWANDA_CRS_PROJ = (
    "+proj=tmerc +lat_0=0 +lon_0=30 "
    "+k=0.9999 +x_0=500000 +y_0=5000000 "
    "+ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs"
)
_RWANDA_TO_WGS84 = Transformer.from_crs(_RWANDA_CRS_PROJ, "EPSG:4326", always_xy=True)


def utm_to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    """Convert Rwanda local TM (Easting, Northing) → (lat, lng) in WGS84."""
    lng, lat = _RWANDA_TO_WGS84.transform(easting, northing)
    return (lat, lng)


# ──────────────────────────────────────────────────────────────────
# Multilingual regex patterns for Rwanda RNLA certificates.
# Rwanda has three official languages — the same certificate is issued in
# Kinyarwanda (rw), English (en), and French (fr) — only the LABELS differ;
# the values (district names, UPI digits, surface number) are identical.
#
# Label mapping per field:
#                EN              RW                    FR
#   UPI       :  UPI             UPI                   UPI            (universal)
#   Area      :  Surface area    Ubuso                 Superficie
#   Province  :  Province        Intara                Province
#   District  :  District        Akarere               District
#   Sector    :  Sector          Umurenge              Secteur
#   Cell      :  Cell            Akagali               Cellule
#   Village   :  Village         Umudugudu             Village
#   Lease     :  Lease period    Imyaka y'ubukode      Bail / Période
# ──────────────────────────────────────────────────────────────────

UPI_PATTERN  = re.compile(r"UPI[:\s]+([0-9]/[0-9]{2}/[0-9]{2}/[0-9]{2}/[0-9]+)", re.I)

# Area unit can be "sqm", "m²", "m2", or Kinyarwanda's "metero kare"
AREA_PATTERN = re.compile(
    r"(?:Surface\s+area|Ubuso|Superficie)\s*[:\s]+([\d.]+)\s*(?:sqm|m[²2]|metero\s+kare)",
    re.I
)

# Each admin field's regex matches its label in any of the three languages,
# then captures the value up to the start of the adjacent field's label.
PROV_PATTERN = re.compile(
    r"(?:Province|Intara)\s*[:\s]+([A-Za-z ]+?)(?:\s+(?:Cell|Akagali|Cellule)|\s*\n)",
    re.I
)
DIST_PATTERN = re.compile(
    r"(?:District|Akarere)\s*[:\s]+([A-Za-z ]+?)(?:\s+(?:Village|Umudugudu)|\s*\n)",
    re.I
)
SECT_PATTERN = re.compile(
    r"(?:Sector|Umurenge|Secteur)\s*[:\s]+([A-Za-z ]+?)(?:\s+(?:Lease|Imyaka|Bail|P[ée]riode)|\s*\n)",
    re.I
)
CELL_PATTERN = re.compile(
    r"(?:Cell|Akagali|Cellule)\s*[:\s]+([A-Za-z ]+?)(?:\s+(?:District|Akarere)|\s*\n)",
    re.I
)
VILL_PATTERN = re.compile(
    r"(?:Village|Umudugudu)\s*[:\s]+([A-Za-z ]+?)(?:\s+(?:Sector|Umurenge|Secteur)|\s*\n)",
    re.I
)

# Coordinate patterns: UTM Zone 35S near Rwanda lies in:
#   Easting:  ~150,000 – 850,000  (6 digits typical for inhabited areas)
#   Northing: ~9,750,000 – 9,830,000 N (or 7-digit value when written
#                                       as 'False Northing from origin')
# Rwanda titles use the 7-digit "false northing" variant like 4781470.
# Easting on inhabited cells is typically 5xx,xxx (six digits).
EASTING_PATTERN  = re.compile(r"\b(5\d{5})\b")        # 500000–599999
NORTHING_PATTERN = re.compile(r"\b(47\d{5})\b|\b(48\d{5})\b")  # 4700000–4899999


def extract_from_pdf_text(pdf_path: Path) -> dict:
    """Extract via pdfplumber — works only when PDF has selectable text."""
    import pdfplumber

    with pdfplumber.open(str(pdf_path)) as pdf:
        full_text = "\n".join(
            (page.extract_text() or "") for page in pdf.pages
        )

    return parse_text(full_text, source="pdf_text", raw_text=full_text)


def parse_text(text: str, source: str = "unknown", raw_text: str | None = None) -> dict:
    """Pull structured fields out of free-text using the regex set."""
    def first(p, t):
        m = p.search(t)
        return m.group(1).strip() if m else None

    upi      = first(UPI_PATTERN, text)
    area     = first(AREA_PATTERN, text)
    province = first(PROV_PATTERN, text)
    district = first(DIST_PATTERN, text)
    sector   = first(SECT_PATTERN, text)
    cell     = first(CELL_PATTERN, text)
    village  = first(VILL_PATTERN, text)

    eastings  = [int(m) for m in EASTING_PATTERN.findall(text)]
    # Northing regex returns tuples (group1, group2) — flatten to non-empty:
    northings = [int(n) for tup in NORTHING_PATTERN.findall(text) for n in tup if n]

    # Use the mean of distinct corners as the parcel centroid
    centroid_e = sum(set(eastings)) / len(set(eastings)) if eastings else None
    centroid_n = sum(set(northings)) / len(set(northings)) if northings else None

    lat, lng = (None, None)
    if centroid_e is not None and centroid_n is not None:
        lat, lng = utm_to_wgs84(centroid_e, centroid_n)

    out = {
        "upi":          upi,
        "surface_sqm":  float(area) if area else None,
        "easting":      centroid_e,
        "northing":     centroid_n,
        "easting_min":  min(eastings) if eastings else None,
        "easting_max":  max(eastings) if eastings else None,
        "northing_min": min(northings) if northings else None,
        "northing_max": max(northings) if northings else None,
        "lat":          lat,
        "lng":          lng,
        "province":     province,
        "district":     district,
        "sector":       sector,
        "cell":         cell,
        "village":      village,
        "source":       source,
    }
    return out


def _run_tesseract(img_path: Path) -> str:
    """Call the tesseract binary directly — sidesteps pytesseract quirks."""
    import subprocess
    proc = subprocess.run(
        ["tesseract", str(img_path), "-", "--psm", "11"],
        capture_output=True,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.decode("utf-8", errors="replace")


def extract_coords_from_pdf_image(pdf_path: Path, workdir: Path) -> dict:
    """Render page-1 of the certificate and OCR the cadastral diagram twice
    (once normal, once rotated 90°) so we catch BOTH the horizontal Easting
    labels AND the vertical Northing labels.
    """
    import fitz
    from PIL import Image

    doc = fitz.open(str(pdf_path))
    pix = doc[0].get_pixmap(dpi=300)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    w, h = img.size
    # Cadastral diagram occupies the bottom ~50% of page 1. Crop tighter so
    # we don't accidentally OCR the lessee's name/ID into our text buffer.
    cad = img.crop((0, int(h * 0.55), w, h))

    # OCR pass 1 — horizontal (catches Easting labels at top/bottom of grid)
    p_h = workdir / "_cad_h.png"
    cad.save(p_h)
    text_h = _run_tesseract(p_h)
    p_h.unlink(missing_ok=True)

    # OCR pass 2 — rotated 90° clockwise (catches Northing labels on sides)
    p_v = workdir / "_cad_v.png"
    cad.rotate(-90, expand=True).save(p_v)
    text_v = _run_tesseract(p_v)
    p_v.unlink(missing_ok=True)

    combined = text_h + "\n" + text_v
    return parse_text(combined, source="pdf_image_ocr", raw_text=combined)


def extract_from_image(img_path: Path) -> dict:
    """OCR a phone photo / scanned image directly with both rotations."""
    from PIL import Image
    img = Image.open(str(img_path))
    workdir = img_path.parent
    p_h = workdir / "_phot_h.png"; img.save(p_h)
    p_v = workdir / "_phot_v.png"; img.rotate(-90, expand=True).save(p_v)
    text = _run_tesseract(p_h) + "\n" + _run_tesseract(p_v)
    p_h.unlink(missing_ok=True); p_v.unlink(missing_ok=True)
    return parse_text(text, source="ocr_image", raw_text=text)


def _ocr_tsv_multi(img_path: Path) -> str:
    """Run Tesseract TSV OCR in multiple PSM modes on both the original image
    AND a contrast-enhanced version. Concatenates all output for robustness on
    low-resolution / compressed screenshots."""
    import subprocess
    from PIL import Image, ImageEnhance, ImageOps

    # Build a contrast-enhanced version that helps OCR on soft/JPEG screenshots
    enhanced_path = img_path.with_name(img_path.stem + "_enh" + img_path.suffix)
    try:
        img = Image.open(img_path).convert("L")           # greyscale
        img = ImageOps.autocontrast(img, cutoff=2)        # stretch contrast
        img = ImageEnhance.Sharpness(img).enhance(2.0)    # sharpen edges
        img = img.point(lambda p: 255 if p > 180 else 0)  # binarise: keeps only dark text
        img.save(enhanced_path)
    except Exception:
        enhanced_path = None

    combined = []
    for source in [img_path] + ([enhanced_path] if enhanced_path else []):
        for psm in ("6", "11", "3"):
            r = subprocess.run(
                ["tesseract", str(source), "-", "--psm", psm, "tsv"],
                capture_output=True
            )
            if r.returncode == 0:
                combined.append(r.stdout.decode("utf-8", errors="replace"))
    if enhanced_path and enhanced_path.exists():
        enhanced_path.unlink(missing_ok=True)
    return "\n".join(combined)


def extract_polygon_from_pil_image(crop, workdir: Path) -> dict:
    """Polygon extraction from any PIL.Image — used by both PDF and image input paths.

    Algorithm:
      1. Auto-upscale small images so Tesseract has enough pixels to work with
      2. OpenCV adaptive threshold + morphological close → isolate parcel boundary
      3. RETR_CCOMP contour hierarchy → find the largest INNER quadrilateral
      4. Tesseract TSV OCR in MULTIPLE PSM modes (3, 6, 11) for robustness,
         on both the image and its -90° rotation
      5. Linear pixel→UTM transform from label positions
      6. UTM → WGS84 via pyproj

    Returns dict with `polygon_wgs84`, `extracted_area_m2`, `pixels_per_metre`,
    OR dict with `error` key on any failure.
    """
    import cv2
    import numpy as np
    import re
    import math
    from PIL import Image

    try:
        # Auto-upscale low-res screenshots: Tesseract needs ≥ 1500 px width to OCR
        # small grid labels reliably. Phone screenshots are often 1080-1290 px wide.
        if crop.size[0] < 1500:
            scale = 2.0
            new_size = (int(crop.size[0] * scale), int(crop.size[1] * scale))
            crop = crop.resize(new_size, Image.LANCZOS)

        # ── OpenCV polygon detection ──────────────────────────────
        gray = cv2.cvtColor(np.array(crop), cv2.COLOR_RGB2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        binary = cv2.adaptiveThreshold(
            blurred, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
            cv2.THRESH_BINARY_INV, 21, 10
        )
        closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE,
                                  np.ones((3, 3), np.uint8), iterations=2)
        contours, hierarchy = cv2.findContours(
            closed, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
        )

        # Discover ALL quadrilateral / pentagon candidates first, sorted by area.
        # We then pick the parcel by area-ratio relative to the largest detected
        # quadrilateral (which is the page outer frame). The parcel sits at
        # 5%–60% of the outer-frame area: smaller than inner frames (>85%) and
        # bigger than text/label boxes (<5%). This works for both compact pages
        # (Rwamagana 1:212 scale, parcel ~53%) and wide pages (Bugesera 1:5000
        # scale, parcel ~15%).
        candidates = []
        for i, c in enumerate(contours):
            area = cv2.contourArea(c)
            if area < 1_000:
                continue
            # Lower epsilon (1.2% of perimeter, was 2.2%) keeps the real vertices
            # of irregular parcels instead of collapsing every shape to a quad.
            approx = cv2.approxPolyDP(c, 0.012 * cv2.arcLength(c, True), True)
            # Accept any closed polygon with 4..20 vertices. Rwandan parcels are
            # frequently 5-, 6-sided or L-shaped — the old 4-6 cap silently
            # dropped them ("polygon just missing").
            if 4 <= len(approx) <= 20:
                parent = hierarchy[0][i][3] if hierarchy is not None else -1
                candidates.append((area, approx, parent, i))

        if not candidates:
            return {"error": "no polygon candidates"}

        candidates.sort(key=lambda x: -x[0])
        outer_area = candidates[0][0]
        # A real parcel is an INNER polygon (has a parent) occupying 3%-85% of
        # the outer page frame: bigger than text/label boxes, smaller than
        # nested inner frames. Widened from 5-60% so unusual scales/shapes
        # survive the filter.
        parcel_candidates = [
            (a, ap) for (a, ap, parent, _) in candidates
            if parent != -1 and (0.03 * outer_area) <= a <= (0.85 * outer_area)
        ]
        if not parcel_candidates:
            return {"error": "no parcel in 3-85% area band"}
        _, approx = parcel_candidates[0]    # largest within the band

        corners_px = [(int(p[0][0]), int(p[0][1])) for p in approx]
        if len(corners_px) < 4:
            return {"error": "fewer than 4 corners"}

        # Order all vertices clockwise around the centroid so the ring is a
        # simple (non-self-intersecting) polygon regardless of vertex count.
        # Works for quads AND irregular many-sided parcels — no rectangle
        # assumption.
        cx = sum(p[0] for p in corners_px) / len(corners_px)
        cy = sum(p[1] for p in corners_px) / len(corners_px)
        clockwise = sorted(corners_px, key=lambda p: math.atan2(p[1] - cy, p[0] - cx))

        # ── OCR with TSV bounding boxes (multi-PSM for robustness) ──
        p_cad = workdir / "_cad_tsv.png"; crop.save(p_cad)
        tsv_h = _ocr_tsv_multi(p_cad)
        rotated = crop.rotate(-90, expand=True)
        p_cad_r = workdir / "_cad_tsv_r.png"; rotated.save(p_cad_r)
        tsv_v = _ocr_tsv_multi(p_cad_r)
        p_cad.unlink(missing_ok=True); p_cad_r.unlink(missing_ok=True)

        def parse_tsv(tsv_text, rotated_inverse=False, orig_h=None):
            out = []
            for row in tsv_text.strip().split("\n")[1:]:
                parts = row.split("\t")
                if len(parts) < 12:
                    continue
                try:
                    left, top, w, h = (int(parts[i]) for i in range(6, 10))
                except ValueError:
                    continue
                text = parts[11]
                rcx, rcy = left + w // 2, top + h // 2
                if rotated_inverse:
                    cx, cy = rcy, (orig_h - 1) - rcx
                else:
                    cx, cy = rcx, rcy
                out.append((text, cx, cy))
            return out

        all_labels = parse_tsv(tsv_h, rotated_inverse=False) + \
                     parse_tsv(tsv_v, rotated_inverse=True, orig_h=crop.size[1])

        eastings = [(int(t), cx) for (t, cx, cy) in all_labels
                    if re.fullmatch(r"5\d{5}", t)]
        northings = [(int(t), cy) for (t, cx, cy) in all_labels
                     if re.fullmatch(r"(47|48)\d{5}", t)]
        if len(eastings) < 2 or len(northings) < 1:
            return {"error": f"need 2 Easting + 1 Northing labels; "
                            f"got E={len(eastings)} N={len(northings)}"}

        # ── Robust pixel→UTM calibration ─────────────────────────
        # Cadastral grids print labels at UNIFORM intervals (e.g. every 5 m).
        # Pixel spacing between consecutive labels is therefore also uniform.
        # That means: the MEDIAN of value-deltas between consecutive labels
        # is the true grid spacing, even if ONE label is OCR-misread.
        #
        # Example (Bugesera): OCR returned 524487, 524493, 524498, 524500.
        # Value deltas: 6, 5, 2 → median = 5 m (drops the '524500' misread).
        # Pixel deltas: 370, 369, 370 → median = 370 px.
        # Calibration: 5 m / 370 px = 0.01351 m/px → 74 px/m (correct).
        #
        # Least-squares fit fails this case because the outlier sits at the
        # extreme of the sample (high leverage). Median-of-deltas doesn't.
        from statistics import median

        def fit_axis(samples):
            """samples = list of (value, pixel_coord).
            Returns (slope_m_per_px, intercept_m) or None if not enough data."""
            if len(samples) < 2:
                return None
            # Median pixel position per distinct value
            by_val = {}
            for v, px in samples:
                by_val.setdefault(v, []).append(px)
            if len(by_val) < 2:
                return None  # need ≥ 2 distinct values to define a slope
            anchors = sorted(((v, median(pxs)) for v, pxs in by_val.items()),
                             key=lambda a: a[1])  # sort by pixel position
            # Compute the implied slope (m per px) for each CONSECUTIVE pair
            # of anchors. Each pair gives one independent measurement of the
            # calibration. The MEDIAN of these per-pair slopes is the robust
            # estimator — a single OCR-misread label only ruins ONE pair, and
            # the median ignores it.
            #
            # Example (Bugesera, OCR misread 524503 as 524500):
            #   Pair 1:  524487→524493   Δpx=370, Δm=6   ⇒ 0.01622 m/px
            #   Pair 2:  524493→524498   Δpx=369, Δm=5   ⇒ 0.01355 m/px
            #   Pair 3:  524498→524500   Δpx=370, Δm=2   ⇒ 0.00541 m/px  ← outlier
            #   median = 0.01355 m/px → 73.8 px/m  (outlier dropped)
            per_pair_slopes = []
            for i in range(1, len(anchors)):
                dpx = anchors[i][1] - anchors[i-1][1]
                dv  = anchors[i][0] - anchors[i-1][0]
                if dpx != 0 and dv != 0:
                    per_pair_slopes.append(dv / dpx)
            if not per_pair_slopes:
                return None
            slope = median(per_pair_slopes)
            # Anchor the line on the first label (in pixel order)
            v0, px0 = anchors[0]
            intercept = v0 - slope * px0
            return float(slope), float(intercept)

        east_fit = fit_axis(eastings)   # [(value, pixel_x), ...]
        north_fit = fit_axis(northings) # [(value, pixel_y), ...]

        if east_fit is None:
            return {"error": "couldn't fit Easting axis"}

        east_slope, east_intercept = east_fit
        if north_fit is not None:
            north_slope, north_intercept = north_fit
        else:
            # Only one Northing label: assume same scale as Easting (square pixels).
            # Use the single labelled value as a single anchor.
            n_val_single, y_single = northings[0]
            # In image y, Northing INCREASES upward, so Northing = -east_slope*py + b
            # → b such that n_val = -east_slope * y_single + b
            north_slope = -east_slope
            north_intercept = n_val_single - north_slope * y_single

        # Pixels-per-metre (for the area / Shoelace check) — use |1/slope|
        px_per_m = abs(1.0 / east_slope) if east_slope != 0 else 0.0
        if px_per_m <= 0:
            return {"error": f"invalid scale fit: {px_per_m}"}

        def to_utm(px, py):
            e = east_slope * px + east_intercept
            n = north_slope * py + north_intercept
            return e, n

        # ── Convert all four corners ──────────────────────────────
        utm_ring = [to_utm(*c) for c in clockwise]
        wgs_ring = []
        for e, n in utm_ring:
            lng, lat = _RWANDA_TO_WGS84.transform(e, n)
            wgs_ring.append((lng, lat))
        wgs_ring.append(wgs_ring[0])  # close ring

        # Shoelace area in m² on UTM coordinates
        n = len(utm_ring)
        s = sum(utm_ring[i][0] * utm_ring[(i+1) % n][1] -
                utm_ring[(i+1) % n][0] * utm_ring[i][1] for i in range(n))
        area_m2 = abs(s) / 2

        return {
            "polygon_wgs84": wgs_ring,        # [(lng,lat), ...] closed ring
            "polygon_utm":   utm_ring,
            "polygon_pixels": clockwise,
            "extracted_area_m2": round(area_m2, 1),
            "pixels_per_metre": round(px_per_m, 3),
        }
    except Exception as e:
        return {"error": f"polygon extraction failed: {e}"}


def extract_polygon_from_pdf(pdf_path: Path, workdir: Path) -> dict:
    """Render page 1 of a cadastral PDF and extract the parcel polygon."""
    import fitz
    from PIL import Image
    doc = fitz.open(str(pdf_path))
    pix = doc[0].get_pixmap(dpi=300)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    crop = img.crop((0, int(img.size[1] * 0.55), img.size[0], img.size[1]))
    return extract_polygon_from_pil_image(crop, workdir)


def extract_polygon_from_image_file(img_path: Path) -> dict:
    """Extract the parcel polygon from a screenshot / phone photo of a cadastral plan."""
    from PIL import Image
    img = Image.open(str(img_path)).convert("RGB")
    return extract_polygon_from_pil_image(img, img_path.parent)


def extract(input_path: Path) -> dict:
    """Top-level dispatch: PDF text first, OCR fallback for coordinates,
    OpenCV contour detection for the polygon."""
    suffix = input_path.suffix.lower()
    if suffix == ".pdf":
        # Step 1: text extraction (admin fields)
        text_result = extract_from_pdf_text(input_path)
        # Step 2: if coordinates are missing, OCR the cadastral diagram
        if text_result.get("easting") is None:
            ocr_result = extract_coords_from_pdf_image(input_path, input_path.parent)
            for k in ("easting", "northing", "easting_min", "easting_max",
                      "northing_min", "northing_max", "lat", "lng"):
                if text_result.get(k) is None and ocr_result.get(k) is not None:
                    text_result[k] = ocr_result[k]
            text_result["source"] = "pdf_text+pdf_image_ocr"
        # Step 3: polygon extraction via OpenCV (fail-soft)
        poly = extract_polygon_from_pdf(input_path, input_path.parent)
        if "error" in poly:
            text_result["polygon_status"] = poly["error"]
        else:
            text_result["polygon_wgs84"]    = poly["polygon_wgs84"]
            text_result["extracted_area_m2"] = poly["extracted_area_m2"]
            text_result["pixels_per_metre"]  = poly["pixels_per_metre"]
            text_result["polygon_status"]   = "extracted"
        return text_result
    elif suffix in {".png", ".jpg", ".jpeg", ".webp", ".tiff"}:
        # Image (screenshot / phone photo of just the cadastral diagram)
        text_result = extract_from_image(input_path)
        # Polygon extraction works on screenshots too — same CV + OCR pipeline
        poly = extract_polygon_from_image_file(input_path)
        if "error" in poly:
            text_result["polygon_status"] = poly["error"]
        else:
            text_result["polygon_wgs84"]    = poly["polygon_wgs84"]
            text_result["extracted_area_m2"] = poly["extracted_area_m2"]
            text_result["pixels_per_metre"]  = poly["pixels_per_metre"]
            text_result["polygon_status"]   = "extracted"
            # Re-derive centroid from the polygon if the standalone OCR didn't get it
            if text_result.get("lat") is None and len(poly["polygon_wgs84"]) >= 4:
                ring = poly["polygon_wgs84"][:-1]   # drop closing point
                text_result["lng"] = sum(p[0] for p in ring) / len(ring)
                text_result["lat"] = sum(p[1] for p in ring) / len(ring)
        return text_result
    else:
        raise ValueError(f"Unsupported file type: {suffix}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: extract_cadastral.py <cert.pdf>", file=sys.stderr)
        sys.exit(2)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"file not found: {path}", file=sys.stderr)
        sys.exit(1)

    result = extract(path)
    print(json.dumps(result, indent=2, ensure_ascii=False))
