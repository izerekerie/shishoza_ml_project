"""SQLite access: connections, one-time schema setup, and the analysis cache.

With gunicorn --workers N, /api/analyse, /api/simulate and /api/alternatives
may each land on a DIFFERENT worker process. An in-memory dict is per-process,
so an analysis stored by one worker is invisible to its siblings. We persist
every analysis to SQLite (shared across workers) and keep _CUT_RECENT only as a
fast in-process cache.
"""

from __future__ import annotations

import json
import sqlite3

from .config import DB_PATH

# analysis_id → last full analyse result (in-process fast path)
_CUT_RECENT: dict = {}


def users_conn():
    """A connection to the app DB with row access by column name."""
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    return con


def init_schema():
    """Create the runtime tables if they don't exist. Safe to call at import;
    idempotent, so a restart against an existing database is a no-op."""
    if not DB_PATH.exists():
        print(f"[boot]   {DB_PATH} not found — alternatives + analysis cache disabled")
        return
    print(f"[boot]   lookup DB: {DB_PATH}")
    try:
        with sqlite3.connect(str(DB_PATH), timeout=10) as _con:
            _con.execute(
                "CREATE TABLE IF NOT EXISTS ANALYSIS_CACHE ("
                "  analysis_id INTEGER PRIMARY KEY,"
                "  payload     TEXT NOT NULL,"
                "  created_at  TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            # Citizen → manager review requests (Phase 1 workflow). Doubles as the
            # RQ4 validation log: who submitted, the parcel, and the model's output.
            _con.execute(
                "CREATE TABLE IF NOT EXISTS REQUESTS ("
                "  request_id        INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  created_at        TEXT NOT NULL,"
                "  citizen_name      TEXT, citizen_phone TEXT, upi TEXT,"
                "  district          TEXT, sector TEXT, sector_id TEXT,"
                "  lat REAL, lng REAL, area_ha REAL,"
                "  risk_level        TEXT, parcel_risk TEXT, neighbourhood_risk TEXT,"
                "  tree_cover_pct    REAL, deforestation_prob REAL, data_source TEXT,"
                "  analysis_id       TEXT,"
                "  status            TEXT NOT NULL DEFAULT 'pending',"
                "  reviewed_by TEXT, reviewed_at TEXT, review_note TEXT)"
            )
            # Citizen accounts (kept separate from the staff USERS table so the
            # USERS role CHECK constraint is untouched). Email + bcrypt password.
            _con.execute(
                "CREATE TABLE IF NOT EXISTS CITIZENS ("
                "  citizen_id    INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  email         VARCHAR(255) NOT NULL UNIQUE,"
                "  password_hash VARCHAR(60)  NOT NULL,"
                "  full_name     VARCHAR(100), phone VARCHAR(30),"
                "  created_at    TEXT DEFAULT CURRENT_TIMESTAMP, last_login TEXT)"
            )
            # Tie each request to the submitting citizen's email. ADD COLUMN is a
            # no-op guard for databases created before this column existed.
            # The last two-row group holds the citizen's intended cut (from the
            # simulation) so the manager sees what they actually propose to clear.
            for col in ("citizen_email TEXT", "reason TEXT", "photo TEXT",
                        "photo_note TEXT", "intended_cut_ha REAL",
                        "after_parcel_risk TEXT", "after_neighbourhood_risk TEXT",
                        "after_tree_cover_pct REAL"):
                try:
                    _con.execute(f"ALTER TABLE REQUESTS ADD COLUMN {col}")
                except sqlite3.OperationalError:
                    pass  # column already present
    except sqlite3.Error as e:
        print(f"[boot]   could not create ANALYSIS_CACHE table: {e}")


def remember_analysis(result):
    """Persist a full analyse result so any gunicorn worker can recall it."""
    aid = result["analysis_id"]
    _CUT_RECENT[aid] = result                       # fast in-process path
    if not DB_PATH.exists():
        return
    try:
        with sqlite3.connect(str(DB_PATH), timeout=10) as con:
            con.execute(
                "INSERT OR REPLACE INTO ANALYSIS_CACHE (analysis_id, payload) "
                "VALUES (?, ?)",
                (aid, json.dumps(result)),
            )
    except sqlite3.Error as e:
        print(f"[warn] analysis cache write failed for {aid}: {e}")


def recall_analysis(aid):
    """Look up a prior analyse result: in-process cache first, then shared DB."""
    hit = _CUT_RECENT.get(aid)
    if hit is not None:
        return hit
    if not DB_PATH.exists():
        return None
    try:
        with sqlite3.connect(str(DB_PATH), timeout=10) as con:
            row = con.execute(
                "SELECT payload FROM ANALYSIS_CACHE WHERE analysis_id = ?", (aid,)
            ).fetchone()
    except sqlite3.Error as e:
        print(f"[warn] analysis cache read failed for {aid}: {e}")
        return None
    if row is None:
        return None
    result = json.loads(row[0])
    _CUT_RECENT[aid] = result                        # warm the in-process cache
    return result


# Create the schema on import, so no route has to check whether it exists first.
init_schema()
