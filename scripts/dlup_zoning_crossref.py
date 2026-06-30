"""Proof-of-concept: cross-reference deforestation against the OFFICIAL district
land-use plan (DLUP) zoning — the "is this clearing a planning violation?" signal.

Idea (from the Rwamagana DLUP ArcGIS service): a clearing in a *protected* zone
(Forest / Buffer / Wetland / Water / Open Space) is far more serious than the same
clearing in an Agriculture zone, where farming is the planned use. This grounds the
forest-manager risk view in official policy, not just a model score.

Scope: Rwamagana district only — each district publishes its own DLUP service
(no national portal), so national rollout is documented future work.

Pipeline:
  1. Page through all DLUP zoning polygons (ArcGIS REST, WGS84).
  2. Spatial-join the national training pixels that fall in Rwamagana into a zone.
  3. Cross-tabulate Hansen-labelled deforestation by land-use category (the honest
     finding — labels are independent of our model).
  4. Headline: deforestation rate in protected vs other zones + how many cleared
     pixels sit in protected zones.

Run:  .venv/bin/python scripts/dlup_zoning_crossref.py
"""

from __future__ import annotations

import json
import urllib.request
import urllib.parse
from pathlib import Path

import pandas as pd
import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from shapely.geometry import Polygon, Point

HERE = Path(__file__).resolve().parent.parent
DATA = HERE / "data" / "raw" / "training_data_national.csv"
OUT_JSON = HERE / "results" / "metrics" / "dlup_zoning_crossref.json"
OUT_PNG  = HERE / "results" / "metrics" / "dlup_zoning_crossref.png"

LAYER = ("https://services7.arcgis.com/htgaiKX6RV2DDGgK/arcgis/rest/services/"
         "Rwamagana_DLUP_14062026/FeatureServer/0/query")
PROTECTED = {"Forest", "Buffer", "Wetland", "Water Body", "Open Space"}


def fetch_dlup() -> gpd.GeoDataFrame:
    """Page through all DLUP polygons (geometry + zoning) in WGS84."""
    feats, offset, page = [], 0, 2000
    while True:
        q = {"where": "1=1", "outFields": "zoning,gen_lu", "returnGeometry": "true",
             "outSR": "4326", "f": "json", "resultOffset": offset,
             "resultRecordCount": page}
        url = LAYER + "?" + urllib.parse.urlencode(q)
        d = json.load(urllib.request.urlopen(url, timeout=120))
        batch = d.get("features", [])
        for f in batch:
            rings = f.get("geometry", {}).get("rings")
            if not rings:
                continue
            # outer ring first; ignore holes for a PoC point-in-polygon
            feats.append({"gen_lu": f["attributes"].get("gen_lu"),
                          "zoning": f["attributes"].get("zoning"),
                          "geometry": Polygon(rings[0])})
        print(f"   fetched {len(feats)} polygons (offset {offset})")
        if len(batch) < page:
            break
        offset += page
    return gpd.GeoDataFrame(feats, crs="EPSG:4326")


def main():
    print("[1/3] Fetch DLUP zoning polygons …")
    zones = fetch_dlup()

    print("[2/3] Load Rwamagana training pixels, spatial-join into zones …")
    df = pd.read_csv(DATA)
    df["lng"] = df[".geo"].apply(lambda s: json.loads(s)["coordinates"][0])
    df["lat"] = df[".geo"].apply(lambda s: json.loads(s)["coordinates"][1])
    pts = gpd.GeoDataFrame(df, geometry=[Point(xy) for xy in zip(df.lng, df.lat)],
                           crs="EPSG:4326")
    joined = gpd.sjoin(pts, zones, how="inner", predicate="within")
    print(f"   {len(joined)} training pixels fell inside a Rwamagana zone")

    print("[3/3] Deforestation (Hansen label) by land-use category:")
    agg = (joined.groupby("gen_lu")
           .agg(n_pixels=("label", "size"), n_deforested=("label", "sum"))
           .reset_index())
    agg["deforestation_rate_pct"] = (agg["n_deforested"] / agg["n_pixels"] * 100).round(1)
    agg["protected"] = agg["gen_lu"].isin(PROTECTED)
    agg = agg.sort_values("deforestation_rate_pct", ascending=False)

    for _, r in agg.iterrows():
        tag = "PROTECTED" if r["protected"] else ""
        print(f"   {r['gen_lu']:<22} n={int(r['n_pixels']):4d}  "
              f"deforested={int(r['n_deforested']):4d}  rate={r['deforestation_rate_pct']:5.1f}%  {tag}")

    prot = joined[joined["gen_lu"].isin(PROTECTED)]
    n_def_total = int(joined["label"].sum())
    n_def_prot  = int(prot["label"].sum())
    headline = {
        "n_pixels_total": int(len(joined)),
        "n_deforested_total": n_def_total,
        "n_deforested_in_protected_zones": n_def_prot,
        "pct_of_clearings_in_protected_zones": round(n_def_prot / n_def_total * 100, 1) if n_def_total else None,
        "deforestation_rate_protected_pct": round(prot["label"].mean() * 100, 1) if len(prot) else None,
        "deforestation_rate_other_pct": round(joined[~joined["gen_lu"].isin(PROTECTED)]["label"].mean() * 100, 1),
    }
    print("\nHEADLINE:")
    print(f"   {headline['pct_of_clearings_in_protected_zones']}% of detected clearings "
          f"fall in PROTECTED zones (Forest/Buffer/Wetland/Water/Open Space)")
    print(f"   deforestation rate: protected={headline['deforestation_rate_protected_pct']}%  "
          f"vs other={headline['deforestation_rate_other_pct']}%")

    # Plot
    fig, ax = plt.subplots(figsize=(9, 5))
    colors = ["#c62828" if p else "#90a4ae" for p in agg["protected"]]
    ax.bar(agg["gen_lu"], agg["deforestation_rate_pct"], color=colors)
    ax.set_ylabel("Deforestation rate (% of pixels, Hansen)")
    ax.set_title("Rwamagana: deforestation by official land-use zone\n(red = protected zone)")
    ax.set_xticklabels(agg["gen_lu"], rotation=40, ha="right", fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT_PNG, dpi=150)

    OUT_JSON.write_text(json.dumps({
        "scope": "Rwamagana district DLUP (per-district service; national = future work)",
        "source": "Rwamagana_DLUP ArcGIS FeatureServer + national training labels (Hansen)",
        "headline": headline,
        "by_landuse": agg.drop(columns="protected").to_dict(orient="records"),
    }, indent=2, default=float))
    print(f"\nSaved → {OUT_JSON}\nSaved → {OUT_PNG}")


if __name__ == "__main__":
    main()
