"""Authentication: staff (USERS) + citizen (CITIZENS) lookups, password checks,
session helpers, and the login_required / admin guards.

Two independent identities share the app: staff (admin / forest_manager) via the
`user_email` session key, and citizens via the `citizen_email` session key.
"""

from __future__ import annotations

import sqlite3

import bcrypt
from flask import jsonify, redirect, session

from .config import DB_PATH
from .db import users_conn


# ── Staff accounts (USERS) ─────────────────────────────────────────────────
def lookup_user(email: str):
    """Find a USERS row by email (case-insensitive). Returns dict or None."""
    if not email:
        return None
    with users_conn() as con:
        row = con.execute(
            "SELECT * FROM USERS WHERE LOWER(email) = LOWER(?) AND is_active = 1",
            (email.strip(),)
        ).fetchone()
    return dict(row) if row else None


def verify_password(plain: str, stored_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), stored_hash.encode())
    except Exception:
        return False


def record_last_login(email: str):
    with users_conn() as con:
        con.execute(
            "UPDATE USERS SET last_login = CURRENT_TIMESTAMP "
            "WHERE LOWER(email) = LOWER(?)", (email,)
        )
        con.commit()


def current_user():
    """Fresh DB read for every request — avoids stale-cache surprises."""
    email = session.get("user_email")
    return lookup_user(email) if email else None


def login_required(fn):
    from functools import wraps

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            return redirect("/login")
        return fn(*args, **kwargs)
    return wrapper


def require_admin():
    """Tiny helper for admin-only endpoints. Returns None on success, or a
    Flask response tuple on failure so handlers can `return` early."""
    user = current_user()
    if not user:
        return jsonify({"error": "Authentication required"}), 401
    if user["role"] != "admin":
        return jsonify({"error": "Admin only"}), 403
    return None


# ── Citizen accounts (separate from staff USERS) ───────────────────────────
def lookup_citizen(email):
    """Find a CITIZENS row by email (case-insensitive), or None."""
    if not email or not DB_PATH.exists():
        return None
    try:
        with sqlite3.connect(str(DB_PATH), timeout=10) as con:
            con.row_factory = sqlite3.Row
            r = con.execute("SELECT * FROM CITIZENS WHERE LOWER(email) = LOWER(?)",
                            (email.strip(),)).fetchone()
            return dict(r) if r else None
    except sqlite3.Error:
        return None


def current_citizen():
    """The signed-in citizen (session key separate from staff logins)."""
    email = session.get("citizen_email")
    return lookup_citizen(email) if email else None
