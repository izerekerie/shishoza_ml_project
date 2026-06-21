"""Precompute per-sector deforestation risk for the Forest Manager dashboard.

For each of Rwanda's 416 administrative sectors:
  1. Find training pixels (from the labelled Nyungwe sample) that fall inside
  2. Compute deforested_pct = mean(label) × 100 over those pixels
  3. Compute median NDVI proxy from the same pixels
  4. Apply the same 3-rule classifier the citizen flow uses
  5. Sectors with < 5 training pixels are marked "not assessed" (grey)

Output: data/sector_risk.json — drop-in for /api/sector-risk endpoint.

Run:  .venv/bin/python scripts/precompute_sector_risk.py
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

HERE = Path(__file__).resolve().parent.parent

print("[1/4] Load training pixels with geometry …")
# National sample (whole country) so every sector with ≥5 labelled pixels gets a
# risk; the old Nyungwe-only training_data.csv only lit up the south-west.
df = pd.read_csv(HERE / "data" / "raw" / "training_data_national.csv")
df["lng"] = df[".geo"].apply(lambda s: json.loads(s)["coordinates"][0])
df["lat"] = df[".geo"].apply(lambda s: json.loads(s)["coordinates"][1])
print(f"   {len(df):,} pixels, classes={df['label'].value_counts().to_dict()}")

print("[2/4] Load 416 sector polygons (RNLA NSDI) …")
sectors = gpd.read_file(HERE / "data" / "geo" / "sectors_wgs84.geojson")
print(f"   {len(sectors)} sectors")

# ── 3. Spatial join — find sector for each training pixel ──────────
print("[3/4] Spatial join — assign each pixel to a sector …")
pix_gdf = gpd.GeoDataFrame(
    df, geometry=[Point(xy) for xy in zip(df["lng"], df["lat"])],
    crs="EPSG:4326"
)
joined = gpd.sjoin(pix_gdf, sectors[["sector_id", "sector", "district", "province",
                                       "geometry"]],
                   how="left", predicate="within")
hits = joined.dropna(subset=["sector_id"])
print(f"   {len(hits):,} pixels mapped to a sector "
      f"({len(hits)/len(df)*100:.1f}% of training set)")

# ── 4. Aggregate per sector ─────────────────────────────────────────
print("[4/4] Compute per-sector risk via the same 3-rule classifier …")
agg = hits.groupby("sector_id").agg(
    n_pixels=("label", "size"),
    n_deforested=("label", "sum"),
    median_ndvi_test=("NDVI_test", "median"),
    median_ndvi_change=("NDVI_change", "median"),
).reset_index()

# Add sector metadata
agg = agg.merge(sectors[["sector_id", "sector", "district", "province"]],
                on="sector_id", how="left")

def classify_sector(row):
    if row["n_pixels"] < 5:
        return "UNKNOWN", 0.0, "insufficient sample"
    deforested_pct = row["n_deforested"] / row["n_pixels"] * 100
    ndvi = row["median_ndvi_test"]
    tree_cover = ndvi * 100
    # Rule 1 — parcel-level proxies
    if tree_cover < 30:
        return "HIGH", deforested_pct, "Rule 1: low tree cover"
    # Rule 2 — neighbourhood
    if deforested_pct > 50 and tree_cover < 50:
        return "HIGH", deforested_pct, "Rule 2: cumulative pressure"
    if deforested_pct > 30:
        return "MEDIUM", deforested_pct, "Rule 3: elevated"
    return "LOW", deforested_pct, "default: stable"

agg[["risk_level", "deforested_pct", "rule_fired"]] = \
    agg.apply(classify_sector, axis=1, result_type="expand")

# Save
out = {
    "generated_at": "2026-06-09",
    "model_version": "rf_D_v1.0.0",
    "summary": {
        "total_sectors":           int(len(sectors)),
        "assessed_sectors":        int((agg["risk_level"] != "UNKNOWN").sum()),
        "high_risk_sectors":       int((agg["risk_level"] == "HIGH").sum()),
        "medium_risk_sectors":     int((agg["risk_level"] == "MEDIUM").sum()),
        "low_risk_sectors":        int((agg["risk_level"] == "LOW").sum()),
    },
    "sectors": agg.to_dict(orient="records"),
}
out_path = HERE / "results" / "application" / "sector_risk.json"
out_path.write_text(json.dumps(out, indent=2, default=float))
print(f"\nSaved → {out_path}")
print(f"\nSummary:")
for k, v in out["summary"].items():
    print(f"  {k:25s}  {v}")
print("\nTop 10 HIGH-risk sectors (cite in dissertation):")
high = agg[agg["risk_level"] == "HIGH"].sort_values("deforested_pct", ascending=False).head(10)
for _, r in high.iterrows():
    print(f"  {r['sector']:25s}  {r['district']:15s}  "
          f"defor={r['deforested_pct']:5.1f}%  n={r['n_pixels']}")
