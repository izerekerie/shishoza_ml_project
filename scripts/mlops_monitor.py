#!/usr/bin/env python
"""
Shishoza MLOps monitor — the "keep the model healthy in production" layer.

This is the operations side of machine learning: a model is not finished when
training ends; it must be watched in production. This module does three jobs:

  1. log_prediction()    — record every /api/analyse result to a CSV log
  2. monitoring_report() — read the log and report DRIFT (are users querying
                           outside the trained Nyungwe zone?) + risk signals
  3. retraining policy   — recommend a RETRAIN when out-of-zone usage is high

The model's own `confidence` / `km_from_training` output is reused as the
drift signal: a LOW-confidence prediction means the parcel is outside the
trained domain. When too many requests are out-of-zone, the model is being
used where it was never validated — the trigger to collect national data and
retrain.

Live demo (needs the Flask app running on :5050):
    .venv/bin/python scripts/mlops_monitor.py --simulate

Re-read the existing log and re-report (no new requests):
    .venv/bin/python scripts/mlops_monitor.py
"""
from __future__ import annotations

import csv
import json
import sys
import urllib.request
from collections import Counter
from pathlib import Path
from statistics import median

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
MON = ROOT / "results" / "monitoring"
LOG = MON / "predictions_log.csv"
SUMMARY = MON / "monitoring_summary.json"
CHART = MON / "monitoring_dashboard.png"

# If more than this % of live requests are outside the trained zone, the model
# is being used where it isn't validated -> recommend a retrain.
OUT_OF_ZONE_THRESHOLD = 30.0

FIELDS = ["lat", "lng", "risk_level", "confidence", "km_from_training", "deforestation_prob"]


def log_prediction(lat, lng, result):
    """Append one /api/analyse result to the production prediction log."""
    MON.mkdir(parents=True, exist_ok=True)
    new_file = not LOG.exists()
    with open(LOG, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            w.writeheader()
        w.writerow({
            "lat": lat,
            "lng": lng,
            "risk_level": result.get("risk_level"),
            "confidence": result.get("confidence"),
            "km_from_training": round(result.get("km_from_training", 0) or 0, 1),
            "deforestation_prob": result.get("deforestation_prob"),
        })


def _analyse(lat, lng):
    req = urllib.request.Request(
        "http://localhost:5050/api/analyse",
        data=json.dumps({"lat": lat, "lng": lng}).encode(),
        headers={"Content-Type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def simulate():
    """Hit the live app with a realistic national-rollout mix of parcels:
    a few inside Nyungwe, many outside it (where most citizens actually are)."""
    coords = [
        (-2.45, 29.10), (-2.50, 29.15), (-2.55, 29.05), (-2.48, 29.20),  # in-zone (Nyungwe)
        (-2.19, 30.07),  # Bugesera (east)
        (-1.95, 30.06),  # Kigali
        (-1.50, 29.60),  # Musanze (north)
        (-1.30, 30.30),  # Nyagatare (north-east)
        (-2.05, 30.40),  # Kirehe (east)
        (-1.70, 30.20),  # Gatsibo (east)
        (-2.60, 29.75),  # Huye (south)
        (-1.48, 29.27),  # Rubavu (north-west)
    ]
    print(f"Sending {len(coords)} analyse requests to the live app and logging each…\n")
    for lat, lng in coords:
        try:
            r = _analyse(lat, lng)
            log_prediction(lat, lng, r)
            print(f"  ({lat:>6}, {lng:>6}) -> {str(r.get('risk_level')):6} | "
                  f"conf={str(r.get('confidence')):4} | {r.get('km_from_training', 0):5.0f} km")
        except Exception as e:
            print(f"  ({lat}, {lng}) FAILED: {e}")


def monitoring_report():
    if not LOG.exists():
        print("No predictions logged yet. Run with --simulate first.")
        return None

    rows = list(csv.DictReader(open(LOG)))
    n = len(rows)
    conf = Counter(r["confidence"] for r in rows)
    risk = Counter(r["risk_level"] for r in rows)
    out_of_zone = conf.get("LOW", 0)
    ooz_pct = out_of_zone / n * 100 if n else 0
    kms = [float(r["km_from_training"]) for r in rows]
    drift = ooz_pct > OUT_OF_ZONE_THRESHOLD

    print("\n" + "=" * 54)
    print("   TreeSight — MODEL MONITORING REPORT")
    print("=" * 54)
    print(f"   Total predictions logged : {n}")
    print(f"   Risk distribution        : {dict(risk)}")
    print(f"   Confidence distribution  : {dict(conf)}")
    print(f"   Out-of-zone (LOW conf)   : {out_of_zone}/{n}  ({ooz_pct:.0f}%)")
    print(f"   Median km from training  : {median(kms):.1f} km")
    print("-" * 54)
    if drift:
        print("   STATUS:  ** DRIFT DETECTED **")
        print(f"   {ooz_pct:.0f}% of requests fall outside the trained Nyungwe")
        print(f"   zone (alert threshold {OUT_OF_ZONE_THRESHOLD:.0f}%).")
        print("   ACTION:  RETRAIN with national data")
        print("            -> run notebooks/01_GEE_Export_National.js,")
        print("               then retrain notebooks/03_Train_Model.ipynb.")
    else:
        print("   STATUS:  OK — usage within the validated domain")
        print("   ACTION:  none; keep monitoring")
    print("=" * 54 + "\n")

    summary = {
        "total_predictions": n,
        "risk_distribution": dict(risk),
        "confidence_distribution": dict(conf),
        "out_of_zone_pct": round(ooz_pct, 1),
        "median_km_from_training": round(median(kms), 1),
        "drift_threshold_pct": OUT_OF_ZONE_THRESHOLD,
        "drift_detected": drift,
        "recommended_action": "RETRAIN_NATIONAL" if drift else "MONITOR",
    }
    MON.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(summary, indent=2))

    # ── Visual dashboard ──
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))

    in_zone = n - out_of_zone
    ax1.bar(["In-zone\n(HIGH conf)", "Out-of-zone\n(LOW conf)"], [in_zone, out_of_zone],
            color=["#1E6B3C", "#C0392B"])
    ax1.axhline(n * OUT_OF_ZONE_THRESHOLD / 100, ls="--", color="#C0392B", lw=1)
    ax1.set_ylabel("requests")
    ax1.set_title(f"Domain coverage — {ooz_pct:.0f}% out-of-zone\n"
                  f"{'DRIFT: retrain recommended' if drift else 'healthy'}",
                  color="#C0392B" if drift else "#1E6B3C", fontsize=11)

    order = ["HIGH", "MEDIUM", "LOW"]
    colours = {"HIGH": "#DC2626", "MEDIUM": "#EA580C", "LOW": "#16A34A"}
    vals = [risk.get(k, 0) for k in order]
    ax2.bar(order, vals, color=[colours[k] for k in order])
    ax2.set_ylabel("predictions")
    ax2.set_title("Predicted risk distribution")

    fig.suptitle("TreeSight — MLOps Monitoring Dashboard", fontweight="bold")
    fig.tight_layout()
    fig.savefig(CHART, dpi=150, bbox_inches="tight")
    print(f"Saved: {LOG.relative_to(ROOT)}")
    print(f"Saved: {SUMMARY.relative_to(ROOT)}")
    print(f"Saved: {CHART.relative_to(ROOT)}")
    return summary


if __name__ == "__main__":
    if "--simulate" in sys.argv:
        simulate()
    monitoring_report()
