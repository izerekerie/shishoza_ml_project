"""Configuration, constants and shared resources for Shishoza.

This is the base module: it imports nothing else from the package, so every
other module can import it without any circular-import risk. It owns the
constants, the resolved paths and the `.env` loader.
"""

from __future__ import annotations

import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Project root = the repository directory, one level up from this package. Every
# model / data / template path is resolved against it, so the app runs the same
# whatever directory it is launched from.
ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv():
    """Load a local .env (KEY=VALUE lines) if present, so email/SMTP settings live
    in one gitignored file instead of being exported by hand. Real environment
    variables always win; the file is entirely optional."""
    envp = ROOT / ".env"
    if not envp.exists():
        return
    for line in envp.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

# ── The 17 model features (Experiment D), in the model's expected order ──
FEATURE_COLS = ['EVI_train', 'NBR_train', 'NDVI_change', 'NDVI_test', 'NDVI_train',
                'NIR_train', 'RED_train', 'SWIR_test', 'SWIR_train', 'VH_VV_ratio',
                'VH_test', 'VH_train', 'VV_test', 'VV_train', 'aspect', 'elevation',
                'slope']

# ── Key file paths ──
MODEL_PATH   = ROOT / "models" / "rf_D_national.pkl"
TRAINING_CSV = ROOT / "data" / "raw" / "training_data_national.csv"
SECTORS_GEOJSON = ROOT / "data" / "geo" / "sectors_wgs84.geojson"
DB_PATH      = ROOT / "data" / "database" / "treesight.db"
PRED_LOG     = ROOT / "results" / "monitoring" / "predictions_log.csv"
UPLOAD_DIR   = ROOT / "data" / "raw" / "external" / "_uploads"

# ── CLEARED_NDVI reference for forward simulation ─────────────────────
# Literature-based value for freshly cleared land in tropical deforestation
# (bare soil + light residual stubble, NDVI ≈ 0.15–0.25 — Pettorelli 2013,
# Mugabowindekwe et al. 2024). We deliberately do NOT use the training-set
# median for class=1 pixels here because:
#   (a) Hansen 2020-22 "loss" pixels often partially re-vegetated by the
#       2023-24 test period (regrowth, planted crops) — median is ≈ 0.70,
#       which would make simulation incorrectly RAISE NDVI after a cut;
#   (b) Cloud Score+ median compositing smooths the immediate post-cut signal.
# Using 0.20 represents the worst-case post-cut NDVI a citizen would observe.
CLEARED_NDVI = 0.20

# ── Earth Engine live-analysis config ──
EE_PROJECT  = os.environ.get("EE_PROJECT", "vocal-orbit-490015-m2")
BASE_START, BASE_END = "2020-01-01", "2022-12-31"   # baseline (matches training)
NOW_START,  NOW_END  = "2025-01-01", "2026-06-30"   # current window
# Cap the live EE pull so a slow/hung Earth Engine drops to the instant local
# path instead of stalling the request.
LIVE_EE_TIMEOUT_S = float(os.environ.get("LIVE_EE_TIMEOUT_S", "15"))
# A successful live pull is remembered per location and re-served until it ages
# past this TTL, matching Sentinel's ~5-day cycle.
LIVE_CACHE_TTL_S = float(os.environ.get("LIVE_CACHE_TTL_S", str(5 * 24 * 3600)))

# Shared worker pool: used for the capped live EE pull and for best-effort,
# off-request-thread email + monitoring writes.
EE_POOL = ThreadPoolExecutor(max_workers=4)

# ── Email notifications (optional; free via Gmail SMTP + an app password) ──
SMTP_HOST  = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT  = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER  = os.environ.get("SMTP_USER")            # e.g. your Gmail address
SMTP_PASS  = os.environ.get("SMTP_PASS")            # a Gmail App Password
SMTP_FROM  = os.environ.get("SMTP_FROM", SMTP_USER or "no-reply@shishoza.rw")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "https://kerie1-shishoza.hf.space")

# Optional Google-Sheet webhook (a Google Apps Script Web App URL) so the
# monitoring log survives the ephemeral container filesystem in deployment.
MONITOR_WEBHOOK_URL = os.environ.get("MONITOR_WEBHOOK_URL")

# Flask secret + upload cap (used when the app is assembled in app_cadastral.py).
# The fallback is a fresh random key per process, never a literal committed here:
# a default in the repo would let anyone forge a session cookie — including an
# admin one — on any deployment that forgot to set SHISHOZA_SECRET. The cost of
# the fallback is that a restart logs everyone out, which is the right way for a
# missing secret to fail.
SECRET_KEY = os.environ.get("SHISHOZA_SECRET")
if not SECRET_KEY:
    SECRET_KEY = secrets.token_hex(32)
    print("[warn] SHISHOZA_SECRET not set — using a random key for this process; "
          "sessions will not survive a restart", flush=True)
MAX_CONTENT_LENGTH = 16 * 1024 * 1024   # 16 MB — covers any phone photo + PDF
