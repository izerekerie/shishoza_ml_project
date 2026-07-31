"""Citizen → manager review-request workflow.

A signed-in citizen submits an analysed parcel for their district forest manager
to review. Each row ties to the citizen's account (email) so the outcome can be
tracked and notified, and doubles as an RQ4 validation record."""

from __future__ import annotations

import datetime
import sqlite3

from flask import Blueprint, jsonify, request, session

from ..config import DB_PATH
from ..auth import current_citizen, current_user, login_required
from ..db import recall_analysis
from ..email_notify import notify_decision
from ..model import sector_for_point

bp = Blueprint("reviews", __name__)


@bp.post("/api/requests")
def api_create_request():
    """Citizen submits an analysed parcel for a manager's technical review.

    Requires a citizen session; routes to the parcel's district manager and
    stores the citizen's stated cutting reason.
    ---
    tags: [Review workflow]
    consumes: [application/json]
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [analysis_id]
          properties:
            analysis_id: {type: integer, description: "ID from a prior /api/analyse", example: 1}
            district:    {type: string, description: "override the auto-detected district", example: "Rusizi"}
            reason:      {type: string, enum: [firewood, timber, farming, income], example: "firewood"}
            photo:       {type: string, description: "optional site photo as a downscaled JPEG data URL (<=1.5 MB)"}
            photo_note:  {type: string, description: "optional caption describing the photo (<=280 chars)"}
    responses:
      200: {description: "Request created; returns request_id, district, sector."}
      401: {description: "Not signed in as a citizen."}
      400: {description: "No prior analysis found for analysis_id."}
    """
    if not DB_PATH.exists():
        return jsonify({"error": "Request store unavailable"}), 503
    citizen = current_citizen()
    if not citizen:
        return jsonify({"error": "Please sign up or log in to request a review"}), 401
    data = request.get_json() or {}
    analysis = recall_analysis(data.get("analysis_id"))
    if not analysis:
        return jsonify({"error": "Please run an analysis before requesting a review"}), 400
    lat, lng = analysis.get("lat"), analysis.get("lng")
    sec = sector_for_point(lat, lng) or {}
    # District routes the request to a manager. Auto-detected from the parcel
    # location, but the citizen can confirm/override it (their choice wins).
    district = (data.get("district") or sec.get("district"))
    sector   = (data.get("sector") or sec.get("sector"))
    now = datetime.datetime.now().isoformat(timespec="seconds")
    # Optional site photo the citizen attached. The browser already downscales it;
    # we only keep a data-URL JPEG within a sane cap (~1.5 MB) and trim the caption.
    photo = data.get("photo")
    if not (isinstance(photo, str) and photo.startswith("data:image/") and len(photo) <= 1_500_000):
        photo = None
    photo_note = (data.get("photo_note") or "").strip()[:280] or None

    # The citizen's intended cut, captured from the on-screen simulation, so the
    # manager reviews what the citizen proposes to clear — not just today's state.
    def _num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    intended_cut_ha = _num(data.get("intended_cut_ha"))
    after_parcel_risk = (data.get("after_parcel_risk") or None)
    after_neighbourhood_risk = (data.get("after_neighbourhood_risk") or None)
    after_tree_cover_pct = _num(data.get("after_tree_cover_pct"))
    try:
        with sqlite3.connect(str(DB_PATH), timeout=10) as con:
            cur = con.execute(
                "INSERT INTO REQUESTS (created_at, citizen_name, citizen_phone, citizen_email, upi, "
                "district, sector, sector_id, lat, lng, area_ha, risk_level, parcel_risk, "
                "neighbourhood_risk, tree_cover_pct, deforestation_prob, data_source, analysis_id, reason, "
                "photo, photo_note, intended_cut_ha, after_parcel_risk, after_neighbourhood_risk, "
                "after_tree_cover_pct) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (now, citizen.get("full_name"), citizen.get("phone"), citizen["email"],
                 (data.get("upi") or analysis.get("upi")), district, sector,
                 sec.get("sector_id"), lat, lng, analysis.get("parcel_area_ha"),
                 analysis.get("risk_level"), analysis.get("parcel_risk"),
                 analysis.get("neighbourhood_risk"), analysis.get("tree_cover_pct"),
                 analysis.get("deforestation_prob"), analysis.get("data_source"),
                 str(data.get("analysis_id")), (data.get("reason") or None),
                 photo, photo_note, intended_cut_ha, after_parcel_risk,
                 after_neighbourhood_risk, after_tree_cover_pct),
            )
            rid = cur.lastrowid
    except sqlite3.Error as e:
        return jsonify({"error": f"Could not save request: {e}"}), 500
    return jsonify({"ok": True, "request_id": rid,
                    "district": district, "sector": sector})


@bp.get("/api/requests")
@login_required
def api_list_requests():
    """Manager/admin: list review requests (scoped to the manager's district).
    ---
    tags: [Review workflow]
    parameters:
      - in: query
        name: status
        type: string
        enum: [pending, approved, rejected]
        description: Optional filter by decision status.
    responses:
      200: {description: "A requests array plus pending/approved/rejected counts."}
      401: {description: "Staff login required."}
    """
    user = current_user()
    status = (request.args.get("status") or "").strip()
    q = "SELECT * FROM REQUESTS"
    conds, params = [], []
    if user.get("district_scope"):
        conds.append("district = ?"); params.append(user["district_scope"])
    if status in ("pending", "approved", "rejected"):
        conds.append("status = ?"); params.append(status)
    if conds:
        q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY (status='pending') DESC, created_at DESC"
    counts = {"pending": 0, "approved": 0, "rejected": 0}
    try:
        with sqlite3.connect(str(DB_PATH), timeout=10) as con:
            con.row_factory = sqlite3.Row
            rows = [dict(r) for r in con.execute(q, params).fetchall()]
            cq, cp = "SELECT status, COUNT(*) FROM REQUESTS", []
            if user.get("district_scope"):
                cq += " WHERE district = ?"; cp.append(user["district_scope"])
            cq += " GROUP BY status"
            for st, n in con.execute(cq, cp).fetchall():
                if st in counts:
                    counts[st] = n
    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"requests": rows, "counts": counts})


@bp.post("/api/requests/<int:req_id>/decision")
@login_required
def api_decide_request(req_id):
    """Manager/admin: approve, flag (reject) or re-open a request.

    A flag requires a note (reason); the citizen is emailed the outcome — with the
    reason + tailored alternatives on a flag, or next steps on approval. Re-opening
    (status=pending) clears the decision. District-scoped.
    ---
    tags: [Review workflow]
    consumes: [application/json]
    parameters:
      - in: path
        name: req_id
        required: true
        type: integer
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [status]
          properties:
            status: {type: string, enum: [approved, rejected, pending], example: "approved"}
            note:   {type: string, description: "required when status=rejected — shown to the citizen"}
    responses:
      200: {description: "Decision saved; citizen emailed if SMTP is configured."}
      400: {description: "Invalid status, or a flag with no reason."}
      403: {description: "Request outside the manager's district."}
      404: {description: "Request not found."}
    """
    user = current_user()
    data = request.get_json() or {}
    status = (data.get("status") or "").strip()
    # 'pending' re-opens a decision made by mistake (no email sent on re-open).
    if status not in ("approved", "rejected", "pending"):
        return jsonify({"error": "status must be 'approved', 'rejected' or 'pending'"}), 400
    note = (data.get("note") or "").strip()
    # A flag/decline must carry a reason — the citizen is shown it.
    if status == "rejected" and not note:
        return jsonify({"error": "Please give a reason when you flag a request — the citizen will see it"}), 400
    now = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        with sqlite3.connect(str(DB_PATH), timeout=10) as con:
            con.row_factory = sqlite3.Row
            row = con.execute(
                "SELECT district, citizen_email, sector, reason FROM REQUESTS WHERE request_id = ?",
                (req_id,)).fetchone()
            if not row:
                return jsonify({"error": "Request not found"}), 404
            if user.get("district_scope") and row["district"] != user["district_scope"]:
                return jsonify({"error": "Request outside your district scope"}), 403
            if status == "pending":          # re-open: clear the decision
                reviewer, reviewed_at, note_val = None, None, None
            else:
                reviewer, reviewed_at, note_val = session.get("user_email"), now, (note or None)
            con.execute(
                "UPDATE REQUESTS SET status=?, reviewed_by=?, reviewed_at=?, review_note=? "
                "WHERE request_id = ?",
                (status, reviewer, reviewed_at, note_val, req_id))
    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 500
    # Best-effort email on a real decision (skipped on re-open, or if SMTP unset).
    if status != "pending":
        notify_decision(row["citizen_email"], req_id, status, note, row["sector"], row["reason"])
    return jsonify({"ok": True})


@bp.get("/api/my-requests")
def api_my_requests():
    """The signed-in citizen's own review requests, newest first.
    ---
    tags: [Review workflow]
    responses:
      200: {description: "The citizen's requests, each with status, reason and the manager's note."}
      401: {description: "Citizen login required."}
    """
    citizen = current_citizen()
    if not citizen:
        return jsonify({"error": "Please log in"}), 401
    try:
        with sqlite3.connect(str(DB_PATH), timeout=10) as con:
            con.row_factory = sqlite3.Row
            rows = [dict(r) for r in con.execute(
                "SELECT request_id, created_at, sector, district, risk_level, parcel_risk, "
                "neighbourhood_risk, tree_cover_pct, status, reviewed_at, review_note, reason, "
                "photo, photo_note "
                "FROM REQUESTS WHERE LOWER(citizen_email) = LOWER(?) ORDER BY created_at DESC",
                (citizen["email"],)).fetchall()]
    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"requests": rows})
