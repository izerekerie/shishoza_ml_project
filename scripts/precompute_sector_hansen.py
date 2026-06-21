"""Rebuild the sector map from TRUE Hansen recent-loss (Decision D-016, fix #1).

Why this replaces the old precompute_sector_risk.py for the sector overview:
  The old map averaged the 0/1 labels of a DELIBERATELY BALANCED training sample,
  so its `deforested_pct` reflected sampling design, not a real rate — it failed the
  Hansen benchmark (r=0.32) and over-flagged already-cleared urban Kigali.

This computes, per sector, an honest measured rate straight from Hansen:
  loss_pct = (forest area LOST in 2020-2024) / (forest area that existed) x 100
where "forest" = Hansen treecover2000 >= 30%. Sectors with almost no forest
(e.g. urban Kigali) are marked NO_FOREST instead of being wrongly flagged HIGH.

Output schema is kept identical to the app's expectation (sector_id, sector,
district, province, risk_level, deforested_pct, n_pixels, rule_fired) so the
Flask app and manager.html need no change to READ it. `deforested_pct` now holds
the real recent-loss %, and `n_pixels` holds the count of 30 m forest pixels.

Run:  .venv/bin/python scripts/precompute_sector_hansen.py
      (needs earthengine authenticate; uses project below.)
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import ee
from shapely.geometry import mapping

HERE        = Path(__file__).resolve().parent.parent
SECTORS_GEO = HERE / "data" / "geo" / "sectors_wgs84.geojson"
OUT_PATH    = HERE / "results" / "application" / "sector_risk.json"
EE_PROJECT  = "vocal-orbit-490015-m2"

ASSET = "UMD/hansen/global_forest_change_2025_v1_13"   # covers loss to 2024
FOREST_TC_MIN = 30          # treecover2000 >= 30% counts as forest (matches labels)
MIN_FOREST_HA = 5.0         # below this, sector has too little forest to assess
# Loss-as-%-of-forest thresholds (documented, explainable):
HIGH_PCT, MED_PCT = 10.0, 3.0


def classify(loss_pct, forest_ha):
    if forest_ha < MIN_FOREST_HA:
        # Use the app's existing "UNKNOWN" (grey) convention so no frontend change
        # is needed; the reason is kept in rule_fired.
        return "UNKNOWN", "minimal forest cover — not assessed"
    if loss_pct >= HIGH_PCT:
        return "HIGH", f"lost >= {HIGH_PCT:.0f}% of forest (2020-2024)"
    if loss_pct >= MED_PCT:
        return "MEDIUM", f"lost {MED_PCT:.0f}-{HIGH_PCT:.0f}% of forest"
    return "LOW", "stable — minimal recent loss"


def main():
    ee.Initialize(project=EE_PROJECT)
    print("Earth Engine ready")

    gfc     = ee.Image(ASSET)
    forest  = gfc.select("treecover2000").gte(FOREST_TC_MIN)
    ly      = gfc.select("lossyear")
    lost    = forest.And(ly.gte(20)).And(ly.lte(24))           # forest lost 2020-2024
    area    = ee.Image.pixelArea()                              # m^2 per pixel
    stack   = (forest.multiply(area).rename("forest_m2")
               .addBands(lost.multiply(area).rename("lost_m2")))

    gdf = gpd.read_file(SECTORS_GEO)
    for c in ("sector_id", "sector", "district", "province"):
        if c in gdf:
            gdf[c] = gdf[c].astype(str)
    gdf["geom_simple"] = gdf.geometry.simplify(0.0005, preserve_topology=True)

    recs = list(gdf[["sector_id", "sector", "district", "province", "geom_simple"]]
                .itertuples(index=False))
    meta = {r.sector_id: r for r in recs}

    print(f"Querying Hansen forest + loss area for {len(recs)} sectors (batched) …")
    sums = {}
    B = 40
    for i in range(0, len(recs), B):
        feats = [ee.Feature(ee.Geometry(mapping(r.geom_simple)),
                            {"sector_id": r.sector_id}) for r in recs[i:i + B]]
        reduced = stack.reduceRegions(collection=ee.FeatureCollection(feats),
                                      reducer=ee.Reducer.sum(), scale=30, tileScale=4)
        for f in reduced.getInfo()["features"]:
            p = f["properties"]
            sums[str(p["sector_id"])] = (p.get("forest_m2") or 0.0, p.get("lost_m2") or 0.0)
        print(f"  …{min(i + B, len(recs))}/{len(recs)}")

    sectors_out = []
    for sid, (forest_m2, lost_m2) in sums.items():
        forest_ha = forest_m2 / 10_000.0
        loss_pct  = (lost_m2 / forest_m2 * 100.0) if forest_m2 > 0 else 0.0
        level, rule = classify(loss_pct, forest_ha)
        m = meta[sid]
        sectors_out.append({
            "sector_id":      sid,
            "sector":         m.sector,
            "district":       m.district,
            "province":       m.province,
            "risk_level":     level,
            "deforested_pct": round(loss_pct, 2),       # now = real recent-loss %
            "n_pixels":       int(round(forest_m2 / 900.0)),  # 30 m forest pixels
            "forest_ha":      round(forest_ha, 1),
            "rule_fired":     rule,
            "source":         "hansen_recent_loss_2020_2024",
        })

    levels = [s["risk_level"] for s in sectors_out]
    out = {
        "generated_at":  "2026-06-21",
        "model_version": "hansen_recent_loss_v1.13",
        "metric":        "forest area lost 2020-2024 as % of sector forest (treecover2000>=30%)",
        "summary": {
            "total_sectors":       len(sectors_out),
            "assessed_sectors":    sum(1 for l in levels if l != "UNKNOWN"),
            "high_risk_sectors":   levels.count("HIGH"),
            "medium_risk_sectors": levels.count("MEDIUM"),
            "low_risk_sectors":    levels.count("LOW"),
            "unknown_sectors":     levels.count("UNKNOWN"),
        },
        "sectors": sorted(sectors_out, key=lambda s: -s["deforested_pct"]),
    }
    OUT_PATH.write_text(json.dumps(out, indent=2, default=float))
    print(f"\nSaved → {OUT_PATH}")
    for k, v in out["summary"].items():
        print(f"  {k:22s} {v}")
    print("\n  (UNKNOWN = minimal forest cover, e.g. urban Kigali — correctly not flagged)")
    print("\nTop 10 HIGH sectors (real Hansen loss):")
    for s in [s for s in out["sectors"] if s["risk_level"] == "HIGH"][:10]:
        print(f"  {s['sector'][:18]:<18} {s['district'][:14]:<14} "
              f"loss={s['deforested_pct']:5.1f}%  forest={s['forest_ha']:.0f}ha")


if __name__ == "__main__":
    main()
