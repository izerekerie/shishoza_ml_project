"""Per-sector risk from current 2025-2026 imagery.

Reads data/raw/sector_features_current.csv (from 02b_GEE_Export_Sectors_Current.js),
runs the model on each pixel, groups by sector, and writes sector_risk.json with
the same scoring and schema as precompute_sector_risk.py:

    score = 0.50 * mean_model_prob + 0.30 * hotspot_pct + 0.20 * median_ndvi_loss
    HIGH >= 0.45 | MEDIUM >= 0.20 | LOW < 0.20 | UNKNOWN if < 5 pixels

The current export has no Hansen label, so n_deforested / deforested_pct are the
count and percent of pixels the model flags as cleared (prob >= 0.50).

Run:  .venv/bin/python scripts/precompute_sector_current.py
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
HOTSPOT_PROB  = 0.70    # pixel is a hotspot if RF prob exceeds this
POSITIVE_PROB = 0.50    # pixel counts as "model-flagged cleared" at/above this

CURRENT_CSV = HERE / "data" / "raw" / "sector_features_current.csv"
RECENT_WINDOW = "2025-01-01 .. 2026-06-30 vs 2020-2022 baseline"

# ── 1. Load model ─────────────────────────────────────────────────────
print("[1/5] Loading rf_D_national.pkl …")
model = pickle.load(open(HERE / "models" / "rf_D_national.pkl", "rb"))
print(f"   {model.n_features_in_} features | classes={list(model.classes_)}")

# ── 2. Load CURRENT-imagery forest pixels ────────────────────────────
print("[2/5] Loading current-imagery pixels …")
if not CURRENT_CSV.exists():
    raise SystemExit(
        f"\nMissing {CURRENT_CSV}\n"
        "Run notebooks/02b_GEE_Export_Sectors_Current.js in Earth Engine first,\n"
        "then download sector_features_current.csv into data/raw/.\n"
    )
df = pd.read_csv(CURRENT_CSV)
df["lng"] = df[".geo"].apply(lambda s: json.loads(s)["coordinates"][0])
df["lat"] = df[".geo"].apply(lambda s: json.loads(s)["coordinates"][1])

# GEE writes -9999 for cloud/no-data pixels; treat as missing and median-impute
# (same column medians the model saw at train time are close enough for scoring).
df[FEATURE_COLS] = df[FEATURE_COLS].replace(-9999, np.nan)
before = len(df)
df = df.dropna(subset=FEATURE_COLS, thresh=len(FEATURE_COLS) - 3)  # keep mostly-complete rows
df[FEATURE_COLS] = df[FEATURE_COLS].fillna(df[FEATURE_COLS].median())
print(f"   {before:,} pixels → {len(df):,} usable after no-data filtering")

# ── 3. RF model predicts probability for every pixel ─────────────────
print("[3/5] Running RF predictions on current pixels …")
X = df[FEATURE_COLS].values
probs = model.predict_proba(X)[:, 1]
df["model_prob"] = probs
df["is_hotspot"] = (probs >= HOTSPOT_PROB).astype(int)
df["is_flagged"] = (probs >= POSITIVE_PROB).astype(int)   # model-predicted cleared
df["ndvi_loss"]  = (-df["NDVI_change"]).clip(lower=0)
print(f"   mean prob={probs.mean():.3f} | "
      f"hotspots (p≥{HOTSPOT_PROB})={df['is_hotspot'].sum():,} "
      f"({df['is_hotspot'].mean()*100:.1f}%)")

# ── 4. Spatial join — assign each pixel to its sector ────────────────
print("[4/5] Spatial join: mapping pixels to sectors …")
sectors = gpd.read_file(HERE / "data" / "geo" / "sectors_wgs84.geojson")
pix_gdf = gpd.GeoDataFrame(
    df, geometry=[Point(xy) for xy in zip(df["lng"], df["lat"])], crs="EPSG:4326",
)
joined = gpd.sjoin(
    pix_gdf,
    sectors[["sector_id", "sector", "district", "province", "geometry"]],
    how="left", predicate="within",
)
hits = joined.dropna(subset=["sector_id"])
print(f"   {len(hits):,} pixels mapped to a sector "
      f"({len(hits) / len(df) * 100:.1f}% of sample)")

# ── 5. Aggregate per sector and compute combined score ────────────────
print("[5/5] Computing combined sector risk scores …")
agg = (
    hits.groupby("sector_id")
    .agg(
        n_pixels          = ("model_prob", "size"),
        n_deforested      = ("is_flagged", "sum"),    # model-flagged, current
        mean_model_prob   = ("model_prob", "mean"),
        max_model_prob    = ("model_prob", "max"),
        hotspot_pct       = ("is_hotspot", "mean"),
        median_ndvi_loss  = ("ndvi_loss",  "median"),
        median_ndvi_change= ("NDVI_change","median"),
    )
    .reset_index()
)
agg = agg.merge(
    sectors[["sector_id", "sector", "district", "province"]],
    on="sector_id", how="left",
)
agg["deforested_pct"] = agg["n_deforested"] / agg["n_pixels"] * 100


def classify_sector(row):
    if row["n_pixels"] < 3:
        return "UNKNOWN", 0.0, "too little forest sampled here to score"
    score = (
        0.50 * row["mean_model_prob"]
      + 0.30 * row["hotspot_pct"]
      + 0.20 * min(float(row["median_ndvi_loss"]), 1.0)
    )
    detail = (
        f"score={score:.3f} | mean_prob={row['mean_model_prob']:.2f} | "
        f"hotspot%={row['hotspot_pct']*100:.1f} | ndvi_loss={row['median_ndvi_loss']:.3f}"
    )
    if score >= HIGH_THRESH:
        return "HIGH",   round(score, 4), detail
    if score >= MEDIUM_THRESH:
        return "MEDIUM", round(score, 4), detail
    return "LOW",        round(score, 4), detail


agg[["risk_level", "risk_score", "rule_fired"]] = agg.apply(
    classify_sector, axis=1, result_type="expand"
)

# ── 6. Save sector_risk.json (same schema the app already reads) ─────
out = {
    "generated_at":  "2026-06-17",
    "model_version": "rf_D_national_v1.0_current_imagery",
    "imagery_window": RECENT_WINDOW,
    "scoring": {
        "method":           "0.50 × mean_model_prob  +  0.30 × hotspot_pct  +  0.20 × median_ndvi_loss",
        "high_threshold":   HIGH_THRESH,
        "medium_threshold": MEDIUM_THRESH,
        "hotspot_definition": f"pixel where RF P(deforestation) ≥ {HOTSPOT_PROB}",
        "rationale": (
            "Same combined score as the training-pixel map, but evaluated on "
            "CURRENT (2025-2026) Sentinel imagery rather than the 2024 training "
            "window, so the sector colour reflects the present state of the land. "
            "deforested_pct = % of sampled pixels the model currently flags as "
            "cleared (prob ≥ 0.50), a present-day prediction not a Hansen count."
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
print(f"\nSaved → {out_path}  (window: {RECENT_WINDOW})\n")
print("Summary:")
for k, v in out["summary"].items():
    print(f"  {k:25s}  {v}")
print("\nTop 10 current HIGH-risk sectors by combined score:")
high = agg[agg["risk_level"] == "HIGH"].sort_values("risk_score", ascending=False).head(10)
for _, r in high.iterrows():
    print(f"  {r['sector']:25s}  {r['district']:15s}  "
          f"score={r['risk_score']:.3f}  mean_prob={r['mean_model_prob']:.2f}  "
          f"hotspot%={r['hotspot_pct']*100:.0f}  n={int(r['n_pixels'])}")
