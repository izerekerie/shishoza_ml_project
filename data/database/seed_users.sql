-- ============================================================
-- TreeSight — seed_users.sql
-- USERS table per the ERD design (Chapter 3, Figure 3.5).
-- bcrypt password hashes for production-grade security.
-- Run via the scripts/seed_users.py helper because bcrypt hashes
-- are generated in Python rather than typed by hand.
-- ============================================================

CREATE TABLE IF NOT EXISTS USERS (
    user_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email            VARCHAR(255) NOT NULL UNIQUE,
    password_hash    VARCHAR(60)  NOT NULL,                    -- bcrypt
    full_name        VARCHAR(100) NOT NULL,
    role             VARCHAR(20)  NOT NULL CHECK (role IN ('admin', 'forest_manager')),
    organisation     VARCHAR(100),
    district_scope   VARCHAR(50),       -- NULL = all districts (admin)
    language         VARCHAR(2)   DEFAULT 'en' CHECK (language IN ('rw','en','fr')),
    created_at       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login       TIMESTAMP,
    is_active        INTEGER      NOT NULL DEFAULT 1
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON USERS (email);
CREATE INDEX        IF NOT EXISTS idx_users_role  ON USERS (role);
