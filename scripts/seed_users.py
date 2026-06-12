"""Seed the USERS table with bcrypt-hashed demo accounts.

Run:  .venv/bin/python scripts/seed_users.py

Idempotent — re-running is safe; existing emails are left alone.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import bcrypt

HERE = Path(__file__).resolve().parent.parent
DB   = HERE / "data" / "database" / "treesight.db"
SCHEMA = HERE / "data" / "database" / "seed_users.sql"

DEMO_USERS = [
    # (email, plain_password, full_name, role, organisation, district_scope, language)
    ("admin@treesight.rw",                 "admin",
     "TreeSight Admin",                "admin",          "TreeSight Project",  None,         "en"),
    ("manager.nyamasheke@treesight.rw",    "nyamasheke",
     "Nyamasheke Forest Manager",      "forest_manager", "Rwanda Forestry Authority", "Nyamasheke", "rw"),
    ("manager.rusizi@treesight.rw",        "rusizi",
     "Rusizi Forest Manager",          "forest_manager", "Rwanda Forestry Authority", "Rusizi",     "rw"),
    ("manager.nyaruguru@treesight.rw",     "nyaruguru",
     "Nyaruguru Forest Manager",       "forest_manager", "Rwanda Forestry Authority", "Nyaruguru",  "rw"),
]


def hash_pwd(pwd: str) -> str:
    return bcrypt.hashpw(pwd.encode(), bcrypt.gensalt(rounds=10)).decode()


def main():
    if not DB.exists():
        print(f"⚠ {DB} not found — run seed_alternatives.sql first")
        return

    schema_sql = SCHEMA.read_text()
    con = sqlite3.connect(str(DB))
    con.executescript(schema_sql)
    con.commit()

    print(f"USERS table ensured in {DB}")
    print()

    cur = con.cursor()
    for (email, pwd, name, role, org, scope, lang) in DEMO_USERS:
        existing = cur.execute(
            "SELECT user_id FROM USERS WHERE email = ?", (email,)
        ).fetchone()
        if existing:
            print(f"  ↻ already exists: {email}  (user_id={existing[0]})")
            continue
        cur.execute(
            "INSERT INTO USERS (email, password_hash, full_name, role, "
            "organisation, district_scope, language) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (email, hash_pwd(pwd), name, role, org, scope, lang),
        )
        print(f"  ✓ inserted: {email}  role={role}  scope={scope or 'ALL'}")
    con.commit()

    # Verify and report
    print()
    print("Final USERS table contents:")
    print(f"  {'user_id':<8}{'email':<40}{'role':<18}{'scope':<14}")
    for row in cur.execute(
        "SELECT user_id, email, role, district_scope FROM USERS ORDER BY user_id"
    ):
        uid, em, r, s = row
        print(f"  {uid:<8}{em:<40}{r:<18}{str(s or 'ALL'):<14}")
    con.close()


if __name__ == "__main__":
    main()
