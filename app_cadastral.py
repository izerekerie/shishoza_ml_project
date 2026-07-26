"""Shishoza — application entry point.

This file stays at the repository root and exposes `app`, so nothing about
deployment changes: gunicorn still runs it as `app_cadastral:app` and Flask's
default template/static folders (`templates/`, `static/`) resolve exactly as
before.

The code that used to live here in one ~2,000-line module now lives in the
`shishoza/` package, split by responsibility:

    shishoza/config.py        constants, env, paths, shared thread pool
    shishoza/db.py            SQLite connections, schema, analysis cache
    shishoza/model.py         model load, features, risk analysis, Earth Engine
    shishoza/auth.py          password checks, sessions, login_required
    shishoza/email_notify.py  citizen decision emails
    shishoza/monitoring.py    prediction / drift logging
    shishoza/routes/*.py      Flask blueprints (pages, analysis, accounts, reviews)

Run locally:  .venv/bin/python app_cadastral.py   →  http://localhost:5050/
"""

from __future__ import annotations

from flask import Flask
from flasgger import Swagger

from shishoza.config import MAX_CONTENT_LENGTH, SECRET_KEY
from shishoza.routes import accounts, analysis, pages, reviews

app = Flask(__name__)
# Secret key for signing the login session cookie. Fixed dev value for the
# capstone demo; set SHISHOZA_SECRET in the environment for any real deployment.
app.secret_key = SECRET_KEY
# Allow up to 16 MB uploads (covers any phone photo + PDF)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

# Register the blueprints. No url_prefix, so every route keeps its exact path.
app.register_blueprint(pages.bp)
app.register_blueprint(analysis.bp)
app.register_blueprint(accounts.bp)
app.register_blueprint(reviews.bp)


# ── Interactive API documentation (Swagger UI) ─────────────────────────
# Browse and try every endpoint live at  http://localhost:5050/apidocs/
# The raw OpenAPI 2.0 spec is served at   http://localhost:5050/apispec_1.json
app.config["SWAGGER"] = {"title": "Shishoza API", "uiversion": 3}
swagger = Swagger(app, template={
    "swagger": "2.0",
    "info": {
        "title": "Shishoza Rwanda — Deforestation Risk API",
        "description": (
            "Backend for the Shishoza MVP. Given a land parcel (from an uploaded "
            "land-title PDF/photo, manual coordinates, or a lat/lng), it assesses "
            "deforestation risk with a tuned Random Forest (Experiment D, F1≈0.79), "
            "forward-simulates a proposed cut, and returns vetted alternatives. "
            "Final-year capstone — Shishoza Rwanda, ALU."
        ),
        "version": "1.0.0",
        "contact": {"email": "twagirinno@gmail.com"},
    },
    "tags": [
        {"name": "Parcel input", "description": "Turn a document or coordinates into a location"},
        {"name": "Risk analysis", "description": "Assess and simulate deforestation risk"},
        {"name": "Guidance", "description": "Alternatives and sector-level dashboards"},
    ],
})


if __name__ == "__main__":
    print("\n  Shishoza running")
    print("   Landing:   http://localhost:5050/")
    print("   Citizen:   http://localhost:5050/citizen")
    print("   Manager:   http://localhost:5050/manager")
    print("   Admin:     http://localhost:5050/admin\n")
    app.run(host="127.0.0.1", port=5050, debug=False)
