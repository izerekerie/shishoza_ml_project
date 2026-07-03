"""RQ4 load test — how well the app delivers risk info under concurrent users.

Targets the read paths that every forest-manager session hits: the sector-risk
choropleth (416 sectors) and the auth/session check. These exercise Flask + the
in-memory model host without calling external services, so the numbers reflect
the server's own delivery capacity.

Run the app under gunicorn first (matches production), then:
    .venv/bin/locust -f scripts/locustfile.py --headless \
        -u 50 -r 5 -t 60s --host http://127.0.0.1:5050 \
        --csv results/performance/loadtest
"""

from locust import HttpUser, task, between


class ManagerUser(HttpUser):
    wait_time = between(1, 3)   # a manager reads the map, then clicks around

    def on_start(self):
        # Sign in once; the session cookie then authorises the sector-risk reads.
        self.client.post("/api/login", json={
            "email": "admin@treesight.rw", "password": "admin"})

    @task(3)
    def sector_risk(self):
        # The choropleth data — the heaviest read a manager page issues.
        self.client.get("/api/sector-risk", name="GET /api/sector-risk")

    @task(1)
    def whoami(self):
        self.client.get("/api/me", name="GET /api/me")

    @task(1)
    def landing(self):
        self.client.get("/", name="GET /")
