"""
Automated test suite for the Shishoza / Umurinzi forest-risk system.

Two layers are exercised, matching the report's Chapter 4 testing sections:

  * Unit tests (4.3.3)        — pure functions in isolation: the three-rule risk
                                classifier, the Rwanda TM -> WGS84 coordinate
                                conversion, and the certificate text parser that
                                turns OCR output into structured fields.
  * Integration tests (4.3.5) — real HTTP requests through Flask's test client
                                across the /api/analyse -> /api/simulate chain
                                and the district-scoped /api/sector-risk endpoint.

Run from the project root:
    python -m pytest tests/test_treesight.py -v
"""
import sqlite3
import sys
from pathlib import Path

import pytest

# Make the project root importable so `import app_cadastral` works no matter
# where pytest is launched from. Importing the app also puts scripts/ on the
# path, which is where the extraction helpers live.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import app_cadastral                                   # noqa: E402
from shishoza import email_notify                       # noqa: E402
from shishoza import model as shishoza_model            # noqa: E402
from shishoza.config import DB_PATH                     # noqa: E402
from shishoza.routes import analysis as analysis_routes  # noqa: E402
from extract_cadastral import utm_to_wgs84, parse_text  # noqa: E402


# Rwanda's national bounding box (WGS84) — every valid parcel must fall inside.
RW_LAT = (-2.95, -1.00)
RW_LNG = (28.80, 30.95)


def _classify(**overrides):
    """Call the real classifier with sensible defaults, overriding only the
    fields a given test cares about. Keeps each test to the one rule it checks."""
    kwargs = dict(
        prob=0.10, ndvi_current=0.80, ndvi_2020=0.80, ndvi_change=0.0,
        deforested_pct_500m=0.0, avg_ndvi_500m=0.80, area_ha=0.05,
        lat=-2.45, lng=29.10, confidence="HIGH", confidence_note="test",
        data_source="unit_test",
    )
    kwargs.update(overrides)
    return shishoza_model.classify_and_build(**kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# 4.3.3  UNIT TESTS — risk classifier
# ─────────────────────────────────────────────────────────────────────────────
class TestRiskClassifier:

    def test_high_risk_when_model_probability_exceeds_threshold(self):
        result = _classify(prob=0.90, ndvi_current=0.50)
        assert result["risk_level"] == "HIGH"
        assert result["rule_fired"] == "Rule 1 (parcel)"

    def test_high_risk_when_tree_cover_below_thirty_percent(self):
        # Low probability, but bare land (NDVI 0.20 -> 20% cover) is still HIGH.
        result = _classify(prob=0.10, ndvi_current=0.20)
        assert result["risk_level"] == "HIGH"
        assert result["rule_fired"] == "Rule 1 (parcel)"

    def test_high_risk_from_cleared_neighbourhood(self):
        # Healthy parcel, but sitting inside a heavily cleared 500 m area.
        result = _classify(prob=0.10, ndvi_current=0.50,
                           deforested_pct_500m=60.0, avg_ndvi_500m=0.90)
        assert result["risk_level"] == "HIGH"
        assert result["rule_fired"] == "Rule 2 (neighbourhood)"

    def test_medium_risk_for_intermediate_probability(self):
        result = _classify(prob=0.50, ndvi_current=0.50, deforested_pct_500m=10.0)
        assert result["risk_level"] == "MEDIUM"
        assert result["rule_fired"] == "Rule 3 (intermediate)"

    def test_low_risk_for_healthy_isolated_parcel(self):
        result = _classify(prob=0.10, ndvi_current=0.85, deforested_pct_500m=0.0)
        assert result["risk_level"] == "LOW"
        assert result["rule_fired"] == "default"

    def test_result_carries_confidence_and_rounded_fields(self):
        result = _classify(prob=0.123456)
        assert result["confidence"] == "HIGH"          # academic-honesty signal
        assert result["deforestation_prob"] == 0.123   # rounded to 3 dp

    def test_subrisks_split_parcel_from_neighbourhood(self):
        parcel, neighbourhood = shishoza_model._subrisks(
            prob=0.80, tree_cover_pct=25.0, deforested_pct_500m=60.0)
        assert parcel == "HIGH"
        assert neighbourhood == "HIGH"


# ─────────────────────────────────────────────────────────────────────────────
# 4.3.3  UNIT TESTS — Rwanda TM -> WGS84 coordinate conversion
# ─────────────────────────────────────────────────────────────────────────────
class TestCoordinateConversion:

    def test_known_parcel_converts_inside_rwanda(self):
        # Easting/Northing from a real Rwanda land title (Swagger example).
        lat, lng = utm_to_wgs84(530412, 4793215)
        assert RW_LAT[0] <= lat <= RW_LAT[1]
        assert RW_LNG[0] <= lng <= RW_LNG[1]

    def test_latitude_is_southern_hemisphere(self):
        lat, _ = utm_to_wgs84(530412, 4793215)
        assert lat < 0                                  # Rwanda is south of the equator

    def test_easting_increase_moves_east(self):
        _, lng_west = utm_to_wgs84(510000, 4793215)
        _, lng_east = utm_to_wgs84(560000, 4793215)
        assert lng_east > lng_west


# ─────────────────────────────────────────────────────────────────────────────
# 4.3.3  UNIT TESTS — certificate text parsing (OCR field extraction)
# ─────────────────────────────────────────────────────────────────────────────
CERTIFICATE_TEXT = """\
UPI: 1/02/03/04/567
Surface area: 512 sqm
Province: Western
District: Nyamasheke
Sector: Kagano
Cell: Ninda
Village: Gaseke
Corner coordinates: 530412 4793215 530420 4793230
"""


class TestCertificateParsing:

    def test_extracts_upi_and_surface_area(self):
        out = parse_text(CERTIFICATE_TEXT, source="unit_test")
        assert out["upi"] == "1/02/03/04/567"
        assert out["surface_sqm"] == 512.0

    def test_extracts_administrative_hierarchy(self):
        out = parse_text(CERTIFICATE_TEXT, source="unit_test")
        assert out["province"] == "Western"
        assert out["district"] == "Nyamasheke"
        assert out["sector"] == "Kagano"

    def test_derives_wgs84_centroid_inside_rwanda(self):
        out = parse_text(CERTIFICATE_TEXT, source="unit_test")
        assert out["lat"] is not None and out["lng"] is not None
        assert RW_LAT[0] <= out["lat"] <= RW_LAT[1]
        assert RW_LNG[0] <= out["lng"] <= RW_LNG[1]

    def test_missing_fields_return_none_not_crash(self):
        out = parse_text("this document has no cadastral fields at all")
        assert out["upi"] is None
        assert out["lat"] is None


# ─────────────────────────────────────────────────────────────────────────────
# 4.3.5  INTEGRATION TESTS — HTTP endpoints via Flask's test client
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def client(monkeypatch_module):
    # Force the deterministic local-model path so tests never depend on a live
    # Earth Engine connection (the endpoint falls back to this in production too).
    # Patch the name where the route module looks it up: analysis.py did
    # `from ..model import ensure_ee`, so patching shishoza.model would not
    # reach the already-bound reference.
    monkeypatch_module.setattr(analysis_routes, "ensure_ee", lambda: False)
    app_cadastral.app.config.update(TESTING=True)
    return app_cadastral.app.test_client()


@pytest.fixture(scope="module")
def monkeypatch_module():
    # A module-scoped monkeypatch (the built-in one is function-scoped).
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


class TestApiIntegration:

    def test_analyse_returns_risk_assessment(self, client):
        resp = client.post("/api/analyse", json={"lat": -2.4521, "lng": 29.1043,
                                                  "area_ha": 0.05})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["risk_level"] in ("HIGH", "MEDIUM", "LOW")
        assert "analysis_id" in body
        assert "confidence" in body                     # honesty signal is always present

    def test_analyse_rejects_missing_coordinates(self, client):
        resp = client.post("/api/analyse", json={"lat": -2.4521})
        assert resp.status_code == 400

    def test_analyse_then_simulate_chain(self, client):
        # Stage 1: analyse a parcel to obtain an analysis_id.
        analysed = client.post("/api/analyse",
                               json={"lat": -2.4521, "lng": 29.1043, "area_ha": 0.05})
        aid = analysed.get_json()["analysis_id"]

        # Stage 2: simulate a cut on that same parcel.
        resp = client.post("/api/simulate",
                          json={"analysis_id": aid, "cut_area_ha": 0.02})
        assert resp.status_code == 200
        body = resp.get_json()
        assert "before" in body and "after" in body
        assert body["after"]["risk_level"] in ("HIGH", "MEDIUM", "LOW")

    def test_simulate_rejects_unknown_analysis_id(self, client):
        resp = client.post("/api/simulate",
                          json={"analysis_id": 99999999, "cut_area_ha": 0.01})
        assert resp.status_code == 404

    def test_sector_risk_requires_authentication(self, client):
        # Unauthenticated request is redirected to the login page, not served.
        resp = client.get("/api/sector-risk")
        assert resp.status_code in (301, 302, 401)

    def test_sector_risk_scoped_for_logged_in_admin(self, client):
        # Set a valid admin session directly (avoids depending on a password).
        with client.session_transaction() as sess:
            sess["user_email"] = "admin@treesight.rw"
        resp = client.get("/api/sector-risk")
        assert resp.status_code == 200
        body = resp.get_json()
        assert "sectors" in body
        assert body["scope"]["view"] == "national"      # admin sees all districts


# ─────────────────────────────────────────────────────────────────────────────
# 4.3.5  INTEGRATION TESTS — citizen→manager review workflow (the new feature)
# ─────────────────────────────────────────────────────────────────────────────
TEST_CITIZEN_EMAIL = "pytest_review@treesight.test"


def _cleanup_review(request_ids=(), citizen_email=None):
    """Remove any rows a workflow test created, so the real database stays clean."""
    try:
        with sqlite3.connect(str(DB_PATH), timeout=10) as con:
            for rid in request_ids:
                if rid is not None:
                    con.execute("DELETE FROM REQUESTS WHERE request_id = ?", (rid,))
            if citizen_email:
                con.execute("DELETE FROM CITIZENS WHERE LOWER(email) = LOWER(?)",
                            (citizen_email,))
    except sqlite3.Error:
        pass


class TestReviewWorkflow:

    def test_create_request_requires_citizen_login(self, client):
        # A parcel cannot be submitted for review without a signed-in citizen.
        anon = app_cadastral.app.test_client()
        resp = anon.post("/api/requests", json={"analysis_id": 12345})
        assert resp.status_code == 401

    def test_review_workflow_end_to_end(self, client, monkeypatch):
        # Full chain: citizen signs up -> analyses a parcel -> submits it for
        # review -> manager lists and decides -> citizen tracks the decision.
        # Separate clients model the two users (distinct sessions); the shared
        # database is what ties their actions together.
        # Neutralise email so the approval step never sends a real message
        # through the configured SMTP account during testing.
        # notify_decision() resolves _send_email from its own module globals at
        # call time, so patching it here silences the send without touching the
        # reviews route.
        monkeypatch.setattr(email_notify, "_send_email", lambda *a, **k: None)
        citizen = app_cadastral.app.test_client()
        manager = app_cadastral.app.test_client()
        _cleanup_review(citizen_email=TEST_CITIZEN_EMAIL)   # start from a clean slate
        req_id = None
        try:
            # 1. Citizen creates an account (opens a citizen session).
            signup = citizen.post("/api/citizen/signup", json={
                "email": TEST_CITIZEN_EMAIL, "password": "testpass123",
                "full_name": "PyTest Citizen"})
            assert signup.status_code == 200, signup.get_json()

            # 2. Citizen analyses a parcel to obtain an analysis_id.
            analysed = citizen.post("/api/analyse",
                                    json={"lat": -2.4521, "lng": 29.1043, "area_ha": 0.05})
            assert analysed.status_code == 200
            aid = analysed.get_json()["analysis_id"]

            # 3. Citizen submits the analysed parcel for manager review.
            submitted = citizen.post("/api/requests",
                                     json={"analysis_id": aid, "reason": "Firewood"})
            assert submitted.status_code == 200, submitted.get_json()
            req_id = submitted.get_json()["request_id"]

            # 4. Manager (admin sees every district) lists requests and finds it.
            with manager.session_transaction() as sess:
                sess["user_email"] = "admin@treesight.rw"
            listed = manager.get("/api/requests")
            assert listed.status_code == 200
            ids = [r["request_id"] for r in listed.get_json()["requests"]]
            assert req_id in ids

            # 4b. A rejection must carry a reason — the citizen is shown it.
            no_reason = manager.post(f"/api/requests/{req_id}/decision",
                                     json={"status": "rejected"})
            assert no_reason.status_code == 400

            # 5. Manager approves the request.
            decided = manager.post(f"/api/requests/{req_id}/decision",
                                   json={"status": "approved", "note": "Within limits"})
            assert decided.status_code == 200

            # 6. Citizen tracks their request and sees the approved decision.
            mine = citizen.get("/api/my-requests")
            assert mine.status_code == 200
            match = [r for r in mine.get_json()["requests"] if r["request_id"] == req_id]
            assert match and match[0]["status"] == "approved"
        finally:
            _cleanup_review(request_ids=[req_id], citizen_email=TEST_CITIZEN_EMAIL)
