# Umurinzi — Deployment plan

This document explains how to deploy Umurinzi to production. The
recommended platform is **Render** with **Docker**, but two backup options
(Render's Python buildpack, Fly.io) are also documented.

---

## 1. Architecture at a glance

```
┌─────────────────────────────────┐
│  Browser (citizen/manager/admin)│
└────────────────┬────────────────┘
                 │ HTTPS
                 ▼
┌─────────────────────────────────┐
│  Render web service (Docker)    │
│  ├── gunicorn ×4 workers        │
│  │   └── app_cadastral.py       │
│  │       ├── /citizen flow      │
│  │       ├── /manager flow      │
│  │       ├── /admin flow        │
│  │       └── /apidocs (Swagger) │
│  └── SQLite USERS + ALTERNATIVES │
└─────────────────────────────────┘
                 │
                 │ At request time NONE of the below are called.
                 │ Everything is precomputed at build time.
                 ▼
                  ✗  Google Earth Engine  (only at training time)
                  ✗  Hansen GFC             (only at training time)
                  ✗  External APIs          (no runtime dependency)
```

**Key property**: zero runtime external dependencies. The container ships
with the trained model, sectors, and Hansen-derived sector_risk.json
pre-loaded. This makes deployments simple, cheap, and reliable.

---

## 2. Why Render + Docker

| Requirement | How Render + Docker meets it |
|---|---|
| Auto-deploy on `git push` | Render listens to GitHub, rebuilds on every commit |
| Reproducible image | `Dockerfile` pins all system + Python deps |
| ≥ 1 GB RAM (we boot at ~600 MB) | Render's Standard tier provides 2 GB |
| HTTPS + custom domain | Free on every tier |
| Logs / metrics | Native log streaming + basic CPU/mem charts |
| OCR-friendly timeout | gunicorn timeout 90 s covers Bugesera-scale PDFs |

---

## 3. Cost estimate

| Component | Plan | Cost / month |
|---|---|---|
| Render web service | **Standard** (2 GB RAM, always-on) | **USD 25** |
| Render web service | Alternative: Starter (512 MB, may OOM on boot) | USD 7 |
| Render web service | Alternative: Free (cold starts, 512 MB) | USD 0 |
| GitHub repo + Actions | Free academic tier | USD 0 |
| Docker Hub | Free for public images | USD 0 |
| Custom domain `umurinzi.rw` | `.rw` registrar via RICTA | ~USD 1 / month amortised (USD 12 / yr) |
| **Total — production demo** |   | **~USD 26 / month** |
| **Total — viva-day only (free tier)** |   | **USD 0** |

> The proposal's original "USD 0" budget assumed PythonAnywhere's free Flask
> tier. Reality: a Flask app that loads a 47 MB ML model + 416 sector
> polygons boots at ~600 MB, which exceeds PythonAnywhere's free 512 MB
> limit. The honest answer is either USD 0 with documented cold-start
> demos, OR USD 25-26 / month for a polished always-on production demo.

---

## 4. Cheaper alternatives if the budget is tight

| Platform | Cost | Catch |
|---|---|---|
| **Fly.io** — Hobby VM, 1 GB | ~USD 3-5 / month | Smaller community; CLI-first; no auto-deploy GUI |
| **Railway** | $5 / month credit free | Free credit runs out fast with always-on |
| **Render Free + cold starts** | USD 0 | 30-second cold start on first request after 15 min idle |
| **DigitalOcean Droplet** | USD 6 / month | Manual ops (SSH, systemd, certificates) |
| **Hetzner CPX11** | EUR 4 / month | Cheapest VM; same manual ops as DO |

**Recommended for the viva**: use **Render Free** for the demo (USD 0) and
acknowledge the ~30s cold-start in the dissertation. Move to Render Standard
($25/mo) if/when a citizen-facing pilot launches.

---

## 5. Step-by-step deploy to Render (Docker mode)

```
1. Sign up at render.com (free tier, no credit card needed initially)

2. Connect your GitHub account: Settings → GitHub → Authorise Render

3. From the Render dashboard:
     New + → Blueprint → Select the Umurinzi repository
   Render reads render.yaml and provisions the service automatically.

4. First build takes ~6-8 minutes (Docker image build + push to Render's
   internal registry). Subsequent builds are ~2-3 minutes (layer cache).

5. Once "Live", note the public URL:
     https://umurinzi-web.onrender.com
   This is automatically HTTPS.

6. Optional — attach a custom domain:
     Service → Settings → Custom Domain → umurinzi.rw
   Render gives you DNS records to add at the .rw registrar.

7. Verify the deployment:
     curl https://umurinzi-web.onrender.com/api/me
     → {"authenticated": false}

8. Demo login:
     Visit https://umurinzi-web.onrender.com/login
     admin@treesight.rw / admin → /admin should load
```

---

## 6. Step-by-step deploy without Docker (Render buildpack mode)

If you prefer not to use Docker:

1. Delete or rename `Dockerfile` so Render picks the Python buildpack
2. Render auto-detects from `requirements.txt`
3. Render reads `Procfile` for the start command
4. Build will install `tesseract-ocr` etc. from `apt-packages` file:

Create `apt-packages` at the repo root:
```
tesseract-ocr
poppler-utils
libgl1
libglib2.0-0
```

Other steps are identical to the Docker path.

---

## 7. Local Docker testing before pushing

```bash
# Build the image
docker build -t umurinzi:latest .

# Run it
docker run -p 5050:5050 -e PORT=5050 umurinzi:latest

# Open http://localhost:5050 in your browser — same demo as production
```

Image size: ~1.2 GB (Python 3.13 slim + tesseract + opencv + sklearn).
Build time: ~6 minutes first time, ~30 seconds with layer cache.

---

## 8. Production checklist before the viva

```
[ ] Set SECRET_KEY env var (NOT the hardcoded demo key)
[ ] Confirm /api/me returns 200 publicly
[ ] Confirm cadastral upload works end-to-end on /citizen
[ ] Confirm manager login + click-to-analyse works
[ ] Confirm admin user-management works
[ ] Set up uptime monitor (UptimeRobot — free) on /api/me
[ ] Document the URL in the dissertation
[ ] Take screenshots of all four dashboards for the dissertation
[ ] Rotate the admin password from the BSc demo default
```

---

## 9. Rollback / failure modes

- **Build fails on Render**: check the build log, usually a missing system
  package. Add to `Dockerfile` line 12 (apt-get install) or `apt-packages`.
- **Container OOMs on boot**: confirm you're on Standard tier (2 GB).
  Starter (512 MB) is not enough for our 600 MB boot footprint.
- **OCR endpoint times out**: gunicorn timeout is 90 s. If a real cert
  takes longer, raise it in `Dockerfile` CMD line.
- **SQLite contention**: SQLite handles ~50 writes/sec which is far above
  expected demo load. If a real pilot ever needs more, migrate USERS to
  Postgres via Render's free 256 MB Postgres tier.
- **Cold start on free tier**: acknowledge in the dissertation; for the
  viva, hit the URL 30 seconds before the demo to wake the worker.

---

## 10. Files involved in deployment

| File | Purpose |
|---|---|
| `Dockerfile` | Builds the production container image |
| `.dockerignore` | Keeps the build context small (skips notebooks/, drafts) |
| `render.yaml` | Render Infrastructure-as-Code blueprint |
| `Procfile` | Alt start command for Render buildpack / Heroku-style platforms |
| `requirements.txt` | Python deps including `gunicorn` |

All of these are tracked in Git; the deployment is reproducible from a
clean clone.
