"""RQ3 — what does the 500 m neighbourhood analysis add over parcel-only?

The risk classifier has three rules. Rule 1 is parcel-only (the parcel's own
model probability + tree cover). Rules 2 and 3 use the 500 m neighbourhood
(share of nearby pixels cleared + how the parcel's greenness compares to its
surroundings). This script quantifies how often the neighbourhood CHANGES the
verdict — i.e. the evidence a parcel-only permit check would miss.

Method: sample parcels from the national set, and for each one reproduce the
app's logic — 25 nearest pixels give the parcel probability and the 500 m
neighbourhood stats. Classify twice: parcel-only (Rule 1) vs full (all rules).

Run:  .venv/bin/python scripts/rq3_neighbourhood_analysis.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pickle
from scipy.spatial import cKDTree

HERE = Path(__file__).resolve().parent.parent
FEATURE_COLS = ['EVI_train', 'NBR_train', 'NDVI_change', 'NDVI_test', 'NDVI_train',
                'NIR_train', 'RED_train', 'SWIR_test', 'SWIR_train', 'VH_VV_ratio',
                'VH_test', 'VH_train', 'VV_test', 'VV_train', 'aspect', 'elevation',
                'slope']
N_SAMPLE = 3000
SEED = 42

model = pickle.load(open(HERE / "models" / "rf_D_national.pkl", "rb"))
df = pd.read_csv(HERE / "data" / "raw" / "training_data_national.csv")
geo = df['.geo'].apply(lambda s: json.loads(s)['coordinates'])
df['lng'] = geo.apply(lambda c: c[0])
df['lat'] = geo.apply(lambda c: c[1])
tree = cKDTree(df[['lat', 'lng']].values)


def classify(prob, ndvi_current, defor_pct_500m, avg_ndvi_500m):
    """Return (parcel_only_level, full_level) using the app's 3 rules."""
    tree_cover_pct = max(0.0, min(100.0, ndvi_current * 100.0))
    rule1_high = (prob > 0.65) or (tree_cover_pct < 30)
    rule2_high = (defor_pct_500m > 50) and (ndvi_current < avg_ndvi_500m * 0.70)
    rule3_med  = (0.35 < prob <= 0.65) and (defor_pct_500m > 0)

    parcel_only = 'HIGH' if rule1_high else 'LOW'          # Rule 1 only
    if rule1_high or rule2_high:
        full = 'HIGH'
    elif rule3_med:
        full = 'MEDIUM'
    else:
        full = 'LOW'
    return parcel_only, full


rng = np.random.default_rng(SEED)
sample_idx = rng.choice(len(df), size=min(N_SAMPLE, len(df)), replace=False)

RANK = {'LOW': 0, 'MEDIUM': 1, 'HIGH': 2}
rows = []
for i in sample_idx:
    lat, lng = df.iloc[i]['lat'], df.iloc[i]['lng']
    _, idx = tree.query([lat, lng], k=25)
    nbrs = df.iloc[idx]
    feats = nbrs[FEATURE_COLS].median().values.reshape(1, -1)
    prob = float(model.predict_proba(feats)[0][1])
    ndvi_current   = float(nbrs['NDVI_test'].median())
    defor_pct_500m = float(nbrs['label'].mean() * 100)
    avg_ndvi_500m  = float(nbrs['NDVI_test'].mean())
    p_only, full = classify(prob, ndvi_current, defor_pct_500m, avg_ndvi_500m)
    rows.append((p_only, full))

res = pd.DataFrame(rows, columns=['parcel_only', 'full'])
res['escalated'] = res.apply(lambda r: RANK[r['full']] > RANK[r['parcel_only']], axis=1)

n = len(res)
escalated = int(res['escalated'].sum())
# Break down which transitions the neighbourhood caused
trans = (res[res['escalated']]
         .groupby(['parcel_only', 'full']).size()
         .rename('n').reset_index())

summary = {
    "method": "3000 sampled national parcels; 25-NN parcel prob + 500 m neighbourhood",
    "n_parcels": n,
    "parcel_only_distribution": res['parcel_only'].value_counts().to_dict(),
    "full_distribution": res['full'].value_counts().to_dict(),
    "n_escalated_by_neighbourhood": escalated,
    "pct_escalated_by_neighbourhood": round(100 * escalated / n, 1),
    "transitions": {f"{r.parcel_only}->{r.full}": int(r.n) for r in trans.itertuples()},
    "interpretation": (
        f"{escalated} of {n} parcels ({round(100*escalated/n,1)}%) were raised to a "
        "higher risk level by the 500 m neighbourhood — clearings a parcel-only "
        "permit check would not flag."
    ),
}

out = HERE / "results" / "metrics" / "rq3_neighbourhood.json"
out.write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))
print(f"\nSaved -> {out}")
