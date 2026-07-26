"""Production prediction log (feeds scripts/mlops_monitor.py).

Every /api/analyse is appended here so we can track real usage and detect drift
(queries outside the trained zone). Same CSV schema the monitor reads.
"""

from __future__ import annotations

import csv
import datetime
import json

from .config import EE_POOL, MONITOR_WEBHOOK_URL, PRED_LOG

_PRED_FIELDS = ["lat", "lng", "risk_level", "confidence", "km_from_training",
                "deforestation_prob"]


def _post_to_monitor_sheet(row):
    """Best-effort append of one prediction to the Google-Sheet webhook. Runs off
    the request thread; any failure is swallowed so it never affects the user."""
    try:
        import urllib.request
        data = json.dumps(row).encode()
        req = urllib.request.Request(
            MONITOR_WEBHOOK_URL, data=data,
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=6)
    except Exception as e:
        print(f"[monitor] sheet webhook skipped: {e}")


def log_prediction(lat, lng, result):
    row = {"lat": lat, "lng": lng,
           "risk_level": result.get("risk_level"),
           "confidence": result.get("confidence"),
           "km_from_training": round(result.get("km_from_training", 0) or 0, 1),
           "deforestation_prob": result.get("deforestation_prob")}
    # 1. Local CSV — fast, but wiped on container restart in deployment.
    try:
        PRED_LOG.parent.mkdir(parents=True, exist_ok=True)
        new = not PRED_LOG.exists()
        with open(PRED_LOG, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=_PRED_FIELDS)
            if new:
                w.writeheader()
            w.writerow(row)
    except Exception as e:
        print(f"[monitor] prediction log skipped: {e}")
    # 2. Persistent Google Sheet — survives restarts; off-thread, best-effort.
    if MONITOR_WEBHOOK_URL:
        sheet_row = {"timestamp": datetime.datetime.now().isoformat(timespec="seconds"), **row}
        EE_POOL.submit(_post_to_monitor_sheet, sheet_row)
