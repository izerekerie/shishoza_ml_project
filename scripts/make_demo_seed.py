"""Regenerate data/database/seed_demo_data.sql from the current database.

Run this after you create accounts, citizens or reviews you want to survive a
Hugging Face rebuild (the free disk is wiped on each deploy). The app applies
the snapshot on boot with INSERT OR IGNORE, so restoring never clobbers newer
data. Usage:  python scripts/make_demo_seed.py
"""
import sqlite3
from pathlib import Path

DB = Path(__file__).parent.parent / "data" / "database" / "treesight.db"
OUT = DB.parent / "seed_demo_data.sql"

# Tables to snapshot, and the column to order by for stable diffs.
TABLES = [("USERS", "user_id"), ("CITIZENS", "citizen_id"), ("REQUESTS", "request_id")]


def sqlval(v):
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def main():
    con = sqlite3.connect(str(DB))
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    lines = [
        "-- seed_demo_data.sql — restores demo users, citizens and reviews after each",
        "-- Hugging Face rebuild (the free disk is ephemeral). Idempotent: INSERT OR",
        "-- IGNORE leaves anything already present untouched. Regenerate with",
        "-- scripts/make_demo_seed.py after you add accounts you want to keep.",
        "",
    ]
    for tbl, order in TABLES:
        try:
            rows = cur.execute(f"SELECT * FROM {tbl} ORDER BY {order}").fetchall()
        except sqlite3.OperationalError:
            continue
        if not rows:
            continue
        cols = rows[0].keys()
        lines.append(f"-- {tbl} ({len(rows)} rows)")
        for r in rows:
            vals = ", ".join(sqlval(r[k]) for k in cols)
            lines.append(f"INSERT OR IGNORE INTO {tbl} ({', '.join(cols)}) VALUES ({vals});")
        lines.append("")
    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT}")
    for tbl, _ in TABLES:
        try:
            n = cur.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            print(f"  {tbl}: {n} rows")
        except sqlite3.OperationalError:
            pass
    con.close()


if __name__ == "__main__":
    main()
