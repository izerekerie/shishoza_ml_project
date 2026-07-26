"""Flask blueprints for Shishoza, grouped by domain.

    pages     — HTML page routes (landing, citizen, manager, admin, …)
    analysis  — parcel input, risk analysis, simulation, guidance, USSD
    accounts  — staff auth + admin user CRUD + citizen auth
    reviews   — citizen → manager review-request workflow

Blueprints declare no url_prefix, so every route keeps the exact path it had in
the original app_cadastral.py — the public URL surface is unchanged.
"""
