"""External validation: do OUR sector deforestation results agree with an
INDEPENDENT, peer-reviewed dataset?  (Decision D-015)

We compare the per-sector `deforested_pct` from `results/application/sector_risk.json`
against the **Hansen Global Forest Change** dataset (Hansen et al., *Science* 2013;
UMD/Google, hosted in Google Earth Engine). Hansen measures annual tree-cover loss at
30 m globally and is the standard academic benchmark for deforestation.

Why this matters for the thesis
-------------------------------
Cross-validation (D-014) only proves the model is consistent with *its own labels*.
This script answers the examiner's real question — "how do you know it's right vs.
existing tools?" — by checking whether the sectors WE flag as high-deforestation are
the same ones an established, independent dataset flags. Agreement = external validity.

What it computes, per sector
----------------------------
  ours_pct    : our deforested_pct (share of sampled pixels labelled deforested)
  hansen_pct  : Hansen tree-cover-loss fraction over the training period (2020-2023*),
                i.e. (loss pixels in 2020-2023) / (all pixels) x 100 inside the sector
Then: Pearson + Spearman correlation across sectors (n_pixels >= 5), and a ranked table.

*Hansen GFC v1.11 currently covers loss up to 2023; our training window is 2020-2024,
 so the last year is not yet in Hansen. State this limitation in the write-up.

Run:  .venv/bin/python scripts/validate_against_hansen.py
      (needs a one-time `earthengine authenticate` first.)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
RISK_JSON   = HERE / "results" / "application" / "sector_risk.json"
SECTORS_GEO = HERE / "data" / "geo" / "sectors_wgs84.geojson"
OUT_JSON    = HERE / "results" / "metrics" / "hansen_benchmark.json"

# Hansen dataset + the loss-year codes for our training window (year - 2000).
HANSEN_ASSET = "UMD/hansen/global_forest_change_2023_v1_11"
LOSS_YEAR_MIN = 20   # 2020
LOSS_YEAR_MAX = 23   # 2023 (latest Hansen covers)


def load_ours() -> dict:
    """sector_id -> {ours_pct, n_pixels, sector, district} from our risk file."""
    data = json.loads(RISK_JSON.read_text())
    out = {}
    for s in data["sectors"]:
        out[str(s["sector_id"])] = {
            "ours_pct":  float(s["deforested_pct"]),
            "n_pixels":  int(s["n_pixels"]),
            "sector":    s.get("sector"),
            "district":  s.get("district"),
            "risk_level": s.get("risk_level"),
        }
    return out


def fetch_hansen_per_sector() -> dict:
    """sector_id -> hansen_pct (Hansen loss fraction in 2020-2023, %). Uses GEE."""
    import ee

    try:
        ee.Initialize()
    except Exception:
        # Not authenticated yet — fail with a clear, actionable message.
        print("ERROR: Earth Engine is not initialised.\n"
              "Run a one-time:  earthengine authenticate\n"
              "then re-run this script.", file=sys.stderr)
        raise

    gfc = ee.Image(HANSEN_ASSET)
    lossyear = gfc.select("lossyear")
    # Binary mask: pixel lost in our training window.
    loss_in_window = lossyear.gte(LOSS_YEAR_MIN).And(lossyear.lte(LOSS_YEAR_MAX))
    # Mean of a 0/1 mask over a region = fraction of region that is loss.
    loss_frac = loss_in_window.rename("hansen_frac")

    # Load our sector polygons as an ee.FeatureCollection (keep sector_id).
    geo = json.loads(SECTORS_GEO.read_text())
    feats = []
    for f in geo["features"]:
        props = f["properties"]
        feats.append(ee.Feature(
            ee.Geometry(f["geometry"]),
            {"sector_id": str(props["sector_id"])},
        ))
    fc = ee.FeatureCollection(feats)

    # Server-side: mean loss fraction per sector at Hansen's native 30 m.
    reduced = loss_frac.reduceRegions(
        collection=fc,
        reducer=ee.Reducer.mean(),
        scale=30,
        tileScale=4,
    )

    out = {}
    for f in reduced.getInfo()["features"]:
        p = f["properties"]
        frac = p.get("mean")
        if frac is not None:
            out[str(p["sector_id"])] = round(float(frac) * 100, 4)
    return out


def correlate(pairs):
    """pairs = list of (ours_pct, hansen_pct). Returns (pearson, spearman, n)."""
    n = len(pairs)
    if n < 3:
        return None, None, n
    xs = [a for a, _ in pairs]
    ys = [b for _, b in pairs]

    def pearson(xs, ys):
        mx = sum(xs) / n; my = sum(ys) / n
        cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        vx = sum((x - mx) ** 2 for x in xs) ** 0.5
        vy = sum((y - my) ** 2 for y in ys) ** 0.5
        return cov / (vx * vy) if vx and vy else None

    def rank(vals):
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        r = [0.0] * len(vals)
        for rank_pos, i in enumerate(order):
            r[i] = rank_pos
        return r

    pear = pearson(xs, ys)
    spear = pearson(rank(xs), rank(ys))
    return pear, spear, n


def main():
    ours = load_ours()
    print(f"[1/3] Loaded {len(ours)} assessed sectors from sector_risk.json")

    print("[2/3] Querying Hansen GFC per sector via Earth Engine "
          "(this can take a minute) …")
    hansen = fetch_hansen_per_sector()
    print(f"      Hansen returned loss for {len(hansen)} sectors")

    # Join on sector_id; keep only reliably-sampled sectors (n_pixels >= 5).
    rows = []
    for sid, o in ours.items():
        if sid in hansen and o["n_pixels"] >= 5:
            rows.append({
                "sector_id": sid,
                "sector":    o["sector"],
                "district":  o["district"],
                "risk_level": o["risk_level"],
                "ours_pct":  round(o["ours_pct"], 2),
                "hansen_pct": hansen[sid],
                "n_pixels":  o["n_pixels"],
            })

    pairs = [(r["ours_pct"], r["hansen_pct"]) for r in rows]
    pear, spear, n = correlate(pairs)

    print("[3/3] Agreement with the independent Hansen benchmark:")
    print(f"      sectors compared : {n}")
    print(f"      Pearson  r       : {pear:.3f}" if pear is not None else "      Pearson  r       : n/a")
    print(f"      Spearman rho     : {spear:.3f}" if spear is not None else "      Spearman rho     : n/a")

    # Show the 10 sectors where we most disagree — useful to inspect/discuss.
    rows.sort(key=lambda r: abs(r["ours_pct"] - r["hansen_pct"]), reverse=True)
    print("\n      Largest disagreements (ours vs Hansen):")
    for r in rows[:10]:
        print(f"        {r['sector']:<18} {r['district']:<14} "
              f"ours={r['ours_pct']:5.1f}%  hansen={r['hansen_pct']:5.1f}%")

    out = {
        "benchmark": "Hansen Global Forest Change (UMD/Google, Science 2013)",
        "hansen_asset": HANSEN_ASSET,
        "loss_window": "2020-2023 (Hansen v1.11 max; training window is 2020-2024)",
        "n_sectors_compared": n,
        "pearson_r": pear,
        "spearman_rho": spear,
        "per_sector": sorted(rows, key=lambda r: -r["ours_pct"]),
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2, default=float))
    print(f"\nSaved → {OUT_JSON}")


if __name__ == "__main__":
    main()
