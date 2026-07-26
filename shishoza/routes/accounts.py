"""Account endpoints: staff auth + admin user CRUD, and citizen auth.

Staff and citizens are deliberately separate identities (different tables,
different session keys). One email may exist in only one of them."""

from __future__ import annotations

import datetime
import sqlite3

import bcrypt
from flask import Blueprint, jsonify, request, session

from ..config import DB_PATH
from ..auth import (current_citizen, current_user, login_required, lookup_citizen,
                    lookup_user, record_last_login, require_admin, verify_password)
from ..db import users_conn

bp = Blueprint("accounts", __name__)


# ── Staff login / session ──────────────────────────────────────────────────
@bp.post("/api/login")
def api_login():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    pwd   = data.get("password") or ""
    user  = lookup_user(email)
    if not user or not verify_password(pwd, user["password_hash"]):
        return jsonify({"error": "Invalid email or password"}), 401
    session["user_email"] = email
    record_last_login(email)
    return jsonify({
        "ok": True,
        "email": email,
        "user": {
            "full_name":      user["full_name"],
            "role":           user["role"],
            "district_scope": user["district_scope"],
            "organisation":   user["organisation"],
            "language":       user["language"],
            "last_login":     user.get("last_login"),
        },
    })


@bp.post("/api/logout")
def api_logout():
    session.pop("user_email", None)
    return jsonify({"ok": True})


@bp.get("/api/me")
def api_me():
    user = current_user()
    if not user:
        return jsonify({"authenticated": False})
    safe = {k: v for k, v in user.items() if k not in ("password_hash",)}
    return jsonify({
        "authenticated": True,
        "email": session.get("user_email"),
        "user": safe,
    })


# ── Admin user management ───────────────────────────────────────────────────
@bp.get("/api/users")
@login_required
def api_users():
    """List all USERS — admin only."""
    err = require_admin()
    if err is not None:
        return err
    with users_conn() as con:
        rows = con.execute(
            "SELECT user_id, email, full_name, role, organisation, "
            "district_scope, language, created_at, last_login, is_active "
            "FROM USERS ORDER BY user_id"
        ).fetchall()
    return jsonify({"users": [dict(r) for r in rows]})


@bp.post("/api/users")
@login_required
def api_users_create():
    """Create a new USER — admin only.
    Body: { email, password, full_name, role, district_scope?, organisation?, language? }
    """
    err = require_admin()
    if err is not None:
        return err
    data = request.get_json() or {}
    required = ["email", "password", "full_name", "role"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"missing fields: {', '.join(missing)}"}), 400
    email = (data["email"] or "").strip().lower()
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        return jsonify({"error": "Please enter a valid email address"}), 400
    if len(data["password"]) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400
    if data["role"] not in ("admin", "forest_manager"):
        return jsonify({"error": "role must be admin or forest_manager"}), 400
    if data["role"] == "forest_manager" and not data.get("district_scope"):
        return jsonify({"error": "forest_manager requires district_scope"}), 400
    if data.get("language") and data["language"] not in ("rw", "en", "fr"):
        return jsonify({"error": "language must be rw, en, or fr"}), 400
    # One email across the whole system: block staff/citizen collisions.
    if lookup_citizen(email):
        return jsonify({"error": "That email is already registered as a citizen account"}), 409

    pw_hash = bcrypt.hashpw(data["password"].encode(), bcrypt.gensalt(rounds=10)).decode()
    try:
        with users_conn() as con:
            cur = con.execute(
                "INSERT INTO USERS (email, password_hash, full_name, role, "
                "organisation, district_scope, language) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (email, pw_hash, data["full_name"],
                 data["role"], data.get("organisation"),
                 data.get("district_scope") if data["role"] == "forest_manager" else None,
                 data.get("language", "en"))
            )
            con.commit()
            new_id = cur.lastrowid
    except sqlite3.IntegrityError:
        return jsonify({"error": "email already exists"}), 409
    return jsonify({"ok": True, "user_id": new_id})


@bp.patch("/api/users/<int:user_id>")
@login_required
def api_users_update(user_id):
    """Update an existing USER (role, scope, organisation, language, is_active) —
    admin only. Use the password endpoint to change passwords."""
    err = require_admin()
    if err is not None:
        return err
    data = request.get_json() or {}
    fields = {}
    for f in ("full_name", "role", "organisation", "district_scope",
              "language", "is_active"):
        if f in data:
            fields[f] = data[f]
    if not fields:
        return jsonify({"error": "no editable fields supplied"}), 400
    if "role" in fields and fields["role"] not in ("admin", "forest_manager"):
        return jsonify({"error": "role must be admin or forest_manager"}), 400
    if "language" in fields and fields["language"] not in ("rw", "en", "fr"):
        return jsonify({"error": "language must be rw, en, or fr"}), 400
    if "is_active" in fields:
        fields["is_active"] = 1 if fields["is_active"] else 0

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    params = list(fields.values()) + [user_id]
    with users_conn() as con:
        cur = con.execute(f"UPDATE USERS SET {set_clause} WHERE user_id = ?", params)
        if cur.rowcount == 0:
            return jsonify({"error": f"user {user_id} not found"}), 404
        con.commit()
    return jsonify({"ok": True, "updated_fields": list(fields.keys())})


@bp.post("/api/users/<int:user_id>/password")
@login_required
def api_users_password(user_id):
    """Admin sets a new password for a user. Body: { password: str }"""
    err = require_admin()
    if err is not None:
        return err
    data = request.get_json() or {}
    new_pwd = data.get("password") or ""
    if len(new_pwd) < 4:
        return jsonify({"error": "password must be at least 4 characters"}), 400
    pw_hash = bcrypt.hashpw(new_pwd.encode(), bcrypt.gensalt(rounds=10)).decode()
    with users_conn() as con:
        cur = con.execute(
            "UPDATE USERS SET password_hash = ? WHERE user_id = ?",
            (pw_hash, user_id)
        )
        if cur.rowcount == 0:
            return jsonify({"error": f"user {user_id} not found"}), 404
        con.commit()
    return jsonify({"ok": True})


@bp.delete("/api/users/<int:user_id>")
@login_required
def api_users_delete(user_id):
    """Soft-delete a user (is_active=0). We never hard-delete because
    PARCEL_ANALYSES rows may reference this user_id."""
    err = require_admin()
    if err is not None:
        return err
    if current_user()["user_id"] == user_id:
        return jsonify({"error": "cannot disable your own admin account"}), 400
    with users_conn() as con:
        cur = con.execute(
            "UPDATE USERS SET is_active = 0 WHERE user_id = ?", (user_id,)
        )
        if cur.rowcount == 0:
            return jsonify({"error": f"user {user_id} not found"}), 404
        con.commit()
    return jsonify({"ok": True})


# ── Citizen accounts ────────────────────────────────────────────────────────
@bp.post("/api/citizen/signup")
def api_citizen_signup():
    """Create a citizen account and start a citizen session.
    ---
    tags: [Citizen accounts]
    consumes: [application/json]
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [email, password]
          properties:
            email:     {type: string, example: "uwase@example.com"}
            password:  {type: string, description: "at least 6 characters", example: "secret12"}
            full_name: {type: string, example: "Uwase M"}
            phone:     {type: string, example: "0788111222"}
    responses:
      200: {description: "Account created; citizen signed in."}
      400: {description: "Invalid email address or password too short."}
      409: {description: "Email already registered (as a citizen or a staff account)."}
    """
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    pwd   = data.get("password") or ""
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        return jsonify({"error": "Please enter a valid email address"}), 400
    if len(pwd) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400
    if lookup_citizen(email):
        return jsonify({"error": "An account with this email already exists — please log in"}), 409
    if lookup_user(email):
        return jsonify({"error": "This email belongs to a staff account. Please use a different email."}), 409
    h = bcrypt.hashpw(pwd.encode(), bcrypt.gensalt()).decode()
    now = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        with sqlite3.connect(str(DB_PATH), timeout=10) as con:
            con.execute(
                "INSERT INTO CITIZENS (email, password_hash, full_name, phone, created_at) "
                "VALUES (?,?,?,?,?)",
                (email, h, (data.get("full_name") or None), (data.get("phone") or None), now))
    except sqlite3.Error as e:
        return jsonify({"error": f"Could not create account: {e}"}), 500
    session["citizen_email"] = email
    return jsonify({"ok": True, "email": email})


@bp.post("/api/citizen/login")
def api_citizen_login():
    """Log a citizen in (separate from the staff /api/login).
    ---
    tags: [Citizen accounts]
    consumes: [application/json]
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required: [email, password]
          properties:
            email:    {type: string, example: "uwase@example.com"}
            password: {type: string, example: "secret12"}
    responses:
      200: {description: "Logged in; citizen session started."}
      401: {description: "Invalid email or password."}
    """
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    c = lookup_citizen(email)
    if not c or not verify_password(data.get("password") or "", c["password_hash"]):
        return jsonify({"error": "Invalid email or password"}), 401
    session["citizen_email"] = email
    try:
        with sqlite3.connect(str(DB_PATH), timeout=10) as con:
            con.execute("UPDATE CITIZENS SET last_login=? WHERE LOWER(email)=LOWER(?)",
                        (datetime.datetime.now().isoformat(timespec="seconds"), email))
    except sqlite3.Error:
        pass
    return jsonify({"ok": True, "email": email})


@bp.post("/api/citizen/logout")
def api_citizen_logout():
    """End the citizen session.
    ---
    tags: [Citizen accounts]
    responses:
      200: {description: "Citizen session cleared."}
    """
    session.pop("citizen_email", None)
    return jsonify({"ok": True})


@bp.get("/api/citizen/me")
def api_citizen_me():
    """Return the signed-in citizen, or {authenticated: false}.
    ---
    tags: [Citizen accounts]
    responses:
      200: {description: "Current citizen (email, full_name, phone) or authenticated:false."}
    """
    c = current_citizen()
    if not c:
        return jsonify({"authenticated": False})
    return jsonify({"authenticated": True, "email": c["email"],
                    "full_name": c.get("full_name"), "phone": c.get("phone")})
