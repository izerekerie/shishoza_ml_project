"""RQ2 — real clearing-patch-size vs detection accuracy (replaces the per-pixel proxy).

The old proxy treated every sampled pixel as its own ~0.09 ha "patch", so all
patches landed in the smallest bucket and no real clearings ever formed. This
computes REAL patch sizes via Hansen connected-components and measures recall
per real size bucket.

Pipeline:
  1. Honest out-of-fold predictions for every pixel via 5-fold cross_val_predict
     (a pixel is scored by a model that never saw it — no leakage).
  2. Hansen loss-2020-2022 mask (matches the label definition in the GEE export)
     -> connectedPixelCount -> real patch size (ha) for each loss pixel.
  3. Sample that patch-size image at each DEFORESTED pixel's coordinates (GEE).
  4. recall = mean(detected) per real size bucket  ->  the RQ2 curve.

Run:  .venv/bin/python scripts/rq2_patch_size.py
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import ee
from sklearn.base import clone
from sklearn.model_selection import cross_val_predict, StratifiedKFold

HERE       = Path(__file__).resolve().parent.parent
DATA       = HERE / "data" / "raw" / "training_data_national.csv"
MODEL      = HERE / "models" / "rf_D_national.pkl"
OUT_JSON   = HERE / "results" / "metrics" / "rq2_patchsize.json"
OUT_PNG    = HERE / "results" / "metrics" / "rq2_patchsize.png"
EE_PROJECT = "vocal-orbit-490015-m2"

# Real patch-size buckets (ha). 0.09 ha = 1 pixel; 0.18 ha = 2 px = parcel standard.
BUCKETS = [(0.0, 0.18, "0.09–0.18 ha\n(1–2 px)"),
           (0.18, 0.45, "0.18–0.45 ha\n(2–5 px)"),
           (0.45, 0.9, "0.45–0.9 ha\n(5–10 px)"),
           (0.9, 1.8, "0.9–1.8 ha\n(10–20 px)"),
           (1.8, 1e9, ">1.8 ha\n(20+ px)")]


def bucket_of(ha):
    for lo, hi, name in BUCKETS:
        if lo < ha <= hi:
            return name
    return None


def main():
    print("[1/4] Load data + model, honest out-of-fold predictions …")
    df = pd.read_csv(DATA)
    df["lng"] = df[".geo"].apply(lambda s: json.loads(s)["coordinates"][0])
    df["lat"] = df[".geo"].apply(lambda s: json.loads(s)["coordinates"][1])

    with open(MODEL, "rb") as f:
        model = pickle.load(f)
    feats = list(getattr(model, "feature_names_in_",
                         [c for c in df.columns
                          if c not in ("system:index", ".geo", "label",
                                       "province", "lng", "lat")]))
    X, y = df[feats].values, df["label"].values

    # Clone the model's config but cap trees so 5-fold CV is tractable; relative
    # recall across buckets is what RQ2 needs, and 200 trees is plenty for that.
    est = clone(model)
    if hasattr(est, "n_estimators"):
        est.set_params(n_estimators=200, n_jobs=-1)
    cv = StratifiedKFold(5, shuffle=True, random_state=42)
    pred = cross_val_predict(est, X, y, cv=cv, n_jobs=-1)
    df["pred"] = pred

    defo = df[df["label"] == 1].copy()
    print(f"   {len(defo):,} deforested pixels; overall recall = {defo['pred'].mean():.3f}")

    print("[2/4] Build Hansen patch-size image (connected components) …")
    ee.Initialize(project=EE_PROJECT)
    # Match the label definition used at export: lossyear 2020-2022, v1.11.
    gfc  = ee.Image("UMD/hansen/global_forest_change_2023_v1_11")
    ly   = gfc.select("lossyear")
    loss = ly.gte(20).And(ly.lte(22)).selfMask()
    patch_px = loss.connectedPixelCount(1024, True)            # connected loss-pixel count
    patch_ha = patch_px.multiply(ee.Image.pixelArea()).divide(10000).rename("patch_ha")

    print("[3/4] Sample real patch size at each deforested pixel (batched) …")
    coords = list(zip(defo["lng"].tolist(), defo["lat"].tolist(), defo["pred"].tolist()))
    rows, B = [], 1000
    for i in range(0, len(coords), B):
        feats_fc = [ee.Feature(ee.Geometry.Point([lng, lat]),
                               {"pred": int(pr), "k": j})
                    for j, (lng, lat, pr) in enumerate(coords[i:i + B])]
        sampled = patch_ha.reduceRegions(ee.FeatureCollection(feats_fc),
                                         ee.Reducer.first(), 30)
        for f in sampled.getInfo()["features"]:
            p = f["properties"]
            if p.get("first") is not None:
                rows.append({"patch_ha": float(p["first"]), "pred": int(p["pred"])})
        print(f"   …{min(i + B, len(coords))}/{len(coords)}")

    res = pd.DataFrame(rows)
    res["bucket"] = res["patch_ha"].apply(bucket_of)
    res = res.dropna(subset=["bucket"])

    print("[4/4] Recall per REAL patch-size bucket:")
    order = [name for _, _, name in BUCKETS]
    table = []
    for name in order:
        sub = res[res["bucket"] == name]
        if len(sub):
            table.append({"bucket": name.replace("\n", " "),
                          "n_patches_pixels": int(len(sub)),
                          "recall": round(float(sub["pred"].mean()), 3)})
            print(f"   {name.replace(chr(10), ' '):<22} n={len(sub):4d}  recall={sub['pred'].mean():.3f}")

    # Plot
    labels = [t["bucket"] for t in table]
    recalls = [t["recall"] for t in table]
    ns = [t["n_patches_pixels"] for t in table]
    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(range(len(labels)), recalls, color="#2e7d32")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels([l.replace(" (", "\n(") for l in labels], fontsize=8)
    ax.set_ylabel("Recall (fraction of clearings detected)")
    ax.set_ylim(0, 1)
    ax.set_title("RQ2 — detection recall vs REAL clearing patch size (30 m, national)")
    for b, n in zip(bars, ns):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.02,
                f"n={n}", ha="center", fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT_PNG, dpi=150)

    out = {
        "method": "Hansen connectedPixelCount real patch sizes; 5-fold out-of-fold RF preds",
        "loss_window": "2020-2022 (matches label definition in GEE export)",
        "n_deforested_pixels": int(len(res)),
        "overall_recall": round(float(defo["pred"].mean()), 3),
        "by_patch_size": table,
    }
    OUT_JSON.write_text(json.dumps(out, indent=2))
    print(f"\nSaved → {OUT_JSON}\nSaved → {OUT_PNG}")


if __name__ == "__main__":
    main()
