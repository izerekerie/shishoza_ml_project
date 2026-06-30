"""HONEST version of the DLUP zoning x deforestation cross-reference.

Measures deforestation by AREA (Hansen loss 2020-2024 / zone area) per land-use
category — avoids the balanced-training-sample bias of the pixel-count version.
Scope: Rwamagana district DLUP only (per-district service; national = future work).

Run:  .venv/bin/python scripts/dlup_zoning_hansen.py
"""

from __future__ import annotations

import json, urllib.request, urllib.parse
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from shapely.geometry import Polygon, mapping
import ee

HERE = Path(__file__).resolve().parent.parent
OUT_JSON = HERE / "results" / "metrics" / "dlup_zoning_hansen.json"
OUT_PNG  = HERE / "results" / "metrics" / "dlup_zoning_hansen.png"
LAYER = ("https://services7.arcgis.com/htgaiKX6RV2DDGgK/arcgis/rest/services/"
         "Rwamagana_DLUP_14062026/FeatureServer/0/query")
EE_PROJECT = "vocal-orbit-490015-m2"
PROTECTED = {"Forest", "Buffer", "Wetland", "Water Body", "Open Space"}


def fetch_dlup():
    feats, offset, page = [], 0, 2000
    while True:
        q = {"where": "1=1", "outFields": "gen_lu", "returnGeometry": "true",
             "outSR": "4326", "f": "json", "resultOffset": offset, "resultRecordCount": page}
        d = json.load(urllib.request.urlopen(LAYER + "?" + urllib.parse.urlencode(q), timeout=120))
        batch = d.get("features", [])
        for f in batch:
            rings = f.get("geometry", {}).get("rings")
            if rings:
                feats.append({"gen_lu": f["attributes"].get("gen_lu"), "geometry": Polygon(rings[0])})
        if len(batch) < page:
            break
        offset += page
    print(f"   {len(feats)} polygons")
    return gpd.GeoDataFrame(feats, crs="EPSG:4326")


def main():
    print("[1/3] Fetch + dissolve DLUP polygons by land-use …")
    z = fetch_dlup()
    dis = z.dissolve(by="gen_lu").reset_index()
    dis["geometry"] = dis.geometry.simplify(0.0003, preserve_topology=True)

    print("[2/3] Hansen loss area vs zone area per category (GEE) …")
    ee.Initialize(project=EE_PROJECT)
    gfc = ee.Image("UMD/hansen/global_forest_change_2025_v1_13")
    ly  = gfc.select("lossyear")
    loss = ly.gte(20).And(ly.lte(24))
    area = ee.Image.pixelArea()
    stack = loss.multiply(area).rename("loss_m2").addBands(area.rename("tot_m2"))

    feats = [ee.Feature(ee.Geometry(mapping(r.geometry)), {"gen_lu": r.gen_lu})
             for r in dis.itertuples()]
    reduced = stack.reduceRegions(ee.FeatureCollection(feats), ee.Reducer.sum(), 30, tileScale=4)

    rows = []
    for f in reduced.getInfo()["features"]:
        p = f["properties"]
        tot = p.get("tot_m2") or 0.0
        lossm = p.get("loss_m2") or 0.0
        rows.append({"gen_lu": p["gen_lu"],
                     "zone_area_ha": round(tot / 1e4, 1),
                     "loss_ha": round(lossm / 1e4, 1),
                     "deforestation_rate_pct": round(lossm / tot * 100, 2) if tot else 0.0,
                     "protected": p["gen_lu"] in PROTECTED})
    rows.sort(key=lambda r: -r["deforestation_rate_pct"])

    print("[3/3] Deforestation by official land-use (AREA-based, Hansen 2020-24):")
    for r in rows:
        print(f"   {r['gen_lu']:<22} zone={r['zone_area_ha']:8.0f}ha  lost={r['loss_ha']:7.1f}ha  "
              f"rate={r['deforestation_rate_pct']:5.2f}%  {'PROTECTED' if r['protected'] else ''}")

    prot_loss = sum(r["loss_ha"] for r in rows if r["protected"])
    tot_loss  = sum(r["loss_ha"] for r in rows)
    headline = {
        "total_loss_ha": round(tot_loss, 1),
        "loss_in_protected_ha": round(prot_loss, 1),
        "pct_of_loss_in_protected_zones": round(prot_loss / tot_loss * 100, 1) if tot_loss else None,
    }
    print(f"\nHEADLINE: {headline['pct_of_loss_in_protected_zones']}% of all Rwamagana forest loss "
          f"(2020-24) occurred in PROTECTED zones ({headline['loss_in_protected_ha']} of {headline['total_loss_ha']} ha)")

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar([r["gen_lu"] for r in rows], [r["deforestation_rate_pct"] for r in rows],
           color=["#c62828" if r["protected"] else "#90a4ae" for r in rows])
    ax.set_ylabel("Deforestation rate (% of zone area lost, Hansen 2020–24)")
    ax.set_title("Rwamagana: deforestation by official land-use zone (area-based)\nred = protected zone")
    ax.set_xticks(range(len(rows)))
    ax.set_xticklabels([r["gen_lu"] for r in rows], rotation=40, ha="right", fontsize=8)
    fig.tight_layout(); fig.savefig(OUT_PNG, dpi=150)

    OUT_JSON.write_text(json.dumps({
        "scope": "Rwamagana DLUP (per-district service; national = future work)",
        "method": "area-based: Hansen loss 2020-2024 / zone area, per land-use category",
        "headline": headline, "by_landuse": rows}, indent=2, default=float))
    print(f"\nSaved → {OUT_JSON}\nSaved → {OUT_PNG}")


if __name__ == "__main__":
    main()
