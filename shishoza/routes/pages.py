"""HTML page routes (server-rendered templates)."""

from __future__ import annotations

from flask import Blueprint, redirect, render_template

from ..auth import current_citizen, current_user, login_required

bp = Blueprint("pages", __name__)


@bp.get("/")
def landing():
    return render_template("landing.html")


@bp.get("/privacy")
def privacy():
    return render_template("privacy.html")


@bp.get("/account")
def citizen_account_page():
    """Dedicated citizen sign-up / log-in page (kept off the crowded sidebar)."""
    return render_template("citizen_auth.html")


@bp.get("/my-reviews")
def my_reviews_page():
    """A citizen's own review requests as a full table (their tracking view)."""
    if not current_citizen():
        return redirect("/account?mode=login")
    return render_template("my_reviews.html")


@bp.get("/citizen")
def citizen():
    return render_template("citizen.html")


@bp.get("/login")
def login_page():
    return render_template("login.html")


@bp.get("/admin")
@login_required
def admin_page():
    if current_user()["role"] != "admin":
        return redirect("/login")
    return render_template("admin.html")


@bp.get("/manager")
@login_required
def manager():
    return render_template("manager.html")


@bp.get("/reviews")
@login_required
def reviews_page():
    """Full-page, filterable table of review requests (scoped by role)."""
    return render_template("reviews.html")
