"""Precompute per-sector deforestation risk using the trained RF model.

TWO-STAGE COMBINED APPROACH
────────────────────────────
Stage 1 — pixel level:
  The RF model (rf_D_national.pkl) predicts P(deforestation) for every
  training pixel. This is a forward-looking PREDICTION, not a label count.

Stage 2 — sector level:
  Three signals are aggregated per sector and combined into one score:

    score = 0.50 × mean_model_prob     ← average RF confidence across sector
          + 0.30 × hotspot_pct         ← fraction of pixels with prob > 0.70
          + 0.20 × median_ndvi_loss    ← magnitude of observed green-cover loss

  This detects both diffuse risk (many moderately risky pixels) and
  concentrated hotspots (a few very high-confidence patches) — weaknesses
  of the old label-count approach that caused the low r = 0.32 correlation.

Classification thresholds:
  HIGH    score ≥ 0.45
  MEDIUM  score ≥ 0.20
  LOW     score <  0.20
  UNKNOWN fewer than 5 training pixels in sector

Run:  .venv/bin/python scripts/precompute_sector_risk.py
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

HERE = Path(__file__).resolve().parent.parent

FEATURE_COLS = [
    'EVI_train', 'NBR_train', 'NDVI_change', 'NDVI_test', 'NDVI_train',
    'NIR_train', 'RED_train', 'SWIR_test', 'SWIR_train', 'VH_VV_ratio',
    'VH_test', 'VH_train', 'VV_test', 'VV_train', 'aspect', 'elevation', 'slope',
]

HIGH_THRESH   = 0.45
MEDIUM_THRESH = 0.20
HOTSPOT_PROB  = 0.70   # pixel is a hotspot if RF prob exceeds this

# ── 1. Load model ─────────────────────────────────────────────────────
print("[1/5] Loading rf_D_national.pkl …")
model = pickle.load(open(HERE / "models" / "rf_D_national.pkl", "rb"))
print(f"   {model.n_features_in_} features | classes={list(model.classes_)}")

# ── 2. Load national training pixels ─────────────────────────────────
print("[2/5] Loading national training pixels …")
df = pd.read_csv(HERE / "data" / "raw" / "training_data_national.csv")
df["lng"] = df[".geo"].apply(lambda s: json.loads(s)["coordinates"][0])
df["lat"] = df[".geo"].apply(lambda s: json.loads(s)["coordinates"][1])
print(f"   {len(df):,} pixels | label distribution: {df['label'].value_counts().to_dict()}")

# ── 3. RF model predicts probability for every pixel ─────────────────
print("[3/5] Running RF predictions on all pixels …")
X = df[FEATURE_COLS].values
probs = model.predict_proba(X)[:, 1]   # P(deforestation) per pixel
df["model_prob"]  = probs
df["is_hotspot"]  = (probs >= HOTSPOT_PROB).astype(int)
# NDVI loss: negative NDVI_change = green cover declined = deforestation signal
df["ndvi_loss"]   = (-df["NDVI_change"]).clip(lower=0)
print(f"   mean prob={probs.mean():.3f} | "
      f"hotspots (p≥{HOTSPOT_PROB})={df['is_hotspot'].sum():,} "
      f"({df['is_hotspot'].mean()*100:.1f}%)")

# ── 4. Spatial join — assign each pixel to its sector ────────────────
print("[4/5] Spatial join: mapping pixels to sectors …")
sectors = gpd.read_file(HERE / "data" / "geo" / "sectors_wgs84.geojson")
pix_gdf = gpd.GeoDataFrame(
    df,
    geometry=[Point(xy) for xy in zip(df["lng"], df["lat"])],
    crs="EPSG:4326",
)
joined = gpd.sjoin(
    pix_gdf,
    sectors[["sector_id", "sector", "district", "province", "geometry"]],
    how="left",
    predicate="within",
)
hits = joined.dropna(subset=["sector_id"])
print(f"   {len(hits):,} pixels mapped to a sector "
      f"({len(hits) / len(df) * 100:.1f}% of training set)")

# ── 5. Aggregate per sector and compute combined score ────────────────
print("[5/5] Computing combined sector risk scores …")
agg = (
    hits.groupby("sector_id")
    .agg(
        n_pixels          = ("label",       "size"),
        n_deforested      = ("label",       "sum"),   # historical reference
        mean_model_prob   = ("model_prob",  "mean"),
        max_model_prob    = ("model_prob",  "max"),
        hotspot_pct       = ("is_hotspot",  "mean"),
        median_ndvi_loss  = ("ndvi_loss",   "median"),
        median_ndvi_change= ("NDVI_change", "median"),
    )
    .reset_index()
)
agg = agg.merge(
    sectors[["sector_id", "sector", "district", "province"]],
    on="sector_id", how="left",
)
agg["deforested_pct"] = agg["n_deforested"] / agg["n_pixels"] * 100


def classify_sector(row):
    if row["n_pixels"] < 5:
        return "UNKNOWN", 0.0, "insufficient sample (<5 pixels)"

    score = (
        0.50 * row["mean_model_prob"]
      + 0.30 * row["hotspot_pct"]
      + 0.20 * min(float(row["median_ndvi_loss"]), 1.0)
    )
    detail = (
        f"score={score:.3f} | "
        f"mean_prob={row['mean_model_prob']:.2f} | "
        f"hotspot%={row['hotspot_pct']*100:.1f} | "
        f"ndvi_loss={row['median_ndvi_loss']:.3f}"
    )
    if score >= HIGH_THRESH:
        return "HIGH",   round(score, 4), detail
    if score >= MEDIUM_THRESH:
        return "MEDIUM", round(score, 4), detail
    return "LOW",        round(score, 4), detail


agg[["risk_level", "risk_score", "rule_fired"]] = agg.apply(
    classify_sector, axis=1, result_type="expand"
)

# ── 6. Save sector_risk.json ──────────────────────────────────────────
out = {
    "generated_at":  "2026-06-29",
    "model_version": "rf_D_national_v1.0_combined_score",
    "scoring": {
        "method":           "0.50 × mean_model_prob  +  0.30 × hotspot_pct  +  0.20 × median_ndvi_loss",
        "high_threshold":   HIGH_THRESH,
        "medium_threshold": MEDIUM_THRESH,
        "hotspot_definition": f"pixel where RF P(deforestation) ≥ {HOTSPOT_PROB}",
        "rationale": (
            "Combines average model confidence (diffuse risk) with hotspot "
            "concentration (localised clearings) and physical NDVI-loss signal "
            "so the sector score is a prediction of future risk rather than a "
            "recount of historical labels."
        ),
    },
    "summary": {
        "total_sectors":    int(len(sectors)),
        "assessed_sectors": int((agg["risk_level"] != "UNKNOWN").sum()),
        "high_risk":        int((agg["risk_level"] == "HIGH").sum()),
        "medium_risk":      int((agg["risk_level"] == "MEDIUM").sum()),
        "low_risk":         int((agg["risk_level"] == "LOW").sum()),
        "unknown":          int((agg["risk_level"] == "UNKNOWN").sum()),
    },
    "sectors": agg.to_dict(orient="records"),
}

out_path = HERE / "results" / "application" / "sector_risk.json"
out_path.write_text(json.dumps(out, indent=2, default=float))
print(f"\nSaved → {out_path}\n")
print("Summary:")
for k, v in out["summary"].items():
    print(f"  {k:25s}  {v}")
print("\nTop 10 HIGH-risk sectors by combined score:")
high = (
    agg[agg["risk_level"] == "HIGH"]
    .sort_values("risk_score", ascending=False)
    .head(10)
)
for _, r in high.iterrows():
    print(f"  {r['sector']:25s}  {r['district']:15s}  "
          f"score={r['risk_score']:.3f}  "
          f"mean_prob={r['mean_model_prob']:.2f}  "
          f"hotspot%={r['hotspot_pct']*100:.0f}  "
          f"n={int(r['n_pixels'])}")
