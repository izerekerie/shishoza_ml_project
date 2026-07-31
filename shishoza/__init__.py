"""Shishoza — Rwanda forest-risk web application (package).

The application entry point stays at the repository root (`app_cadastral.py`,
served by gunicorn as `app_cadastral:app`) so deployment is unchanged. This
package holds the split-out pieces that file used to contain in one place:

    config          — env loading, constants, paths, shared thread pool
    db              — SQLite connections, schema, analysis cache
    model           — model load, feature engineering, risk analysis, Earth Engine
    auth            — password checks, session helpers, login_required
    email_notify    — SMTP decision emails
    monitoring      — prediction logging / drift log
    routes/         — Flask blueprints (pages, analysis, accounts, reviews)

Nothing here creates the Flask app; `app_cadastral.py` assembles it from these
modules and registers the blueprints.
"""
