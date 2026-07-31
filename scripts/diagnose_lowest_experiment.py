"""Why does the lowest-scoring experiment (A, optical-only) underperform?

Instead of assuming the cause, this measures it. It trains Experiment A (optical
only) and Experiment D (all 17 features) on the same split, finds the test pixels
A gets WRONG that D gets RIGHT ("rescues"), and checks whether those rescued pixels
have distinctive radar/terrain values — the exact features A is missing. If they
do, that is direct evidence of what caused A's lower F1.

Run:  .venv/bin/python scripts/diagnose_lowest_experiment.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import f1_score

HERE = Path(__file__).resolve().parent.parent
df = pd.read_csv(HERE / "data" / "raw" / "training_data_national.csv")

OPTICAL = ['EVI_train', 'NBR_train', 'NDVI_change', 'NDVI_test', 'NDVI_train',
           'NIR_train', 'RED_train', 'SWIR_test', 'SWIR_train']            # Exp A (9)
RADAR   = ['VH_VV_ratio', 'VH_test', 'VH_train', 'VV_test', 'VV_train']    # added in C/D
TERRAIN = ['aspect', 'elevation', 'slope']                                # added in B/D
ALL17   = OPTICAL + RADAR + TERRAIN                                        # Exp D (17)

y = df['label'].values.astype(int)
tr, te = train_test_split(range(len(df)), test_size=0.2, random_state=42, stratify=y)

def fit(cols):
    m = RandomForestClassifier(n_estimators=200, max_depth=20, min_samples_leaf=5,
                               class_weight='balanced', random_state=42, n_jobs=-1)
    m.fit(df[cols].values[tr], y[tr])
    return m

A, D = fit(OPTICAL), fit(ALL17)
predA = A.predict(df[OPTICAL].values[te])
predD = D.predict(df[ALL17].values[te])
yte = y[te]

f1A, f1D = f1_score(yte, predA), f1_score(yte, predD)
A_wrong = predA != yte
rescued = A_wrong & (predD == yte)          # A got it wrong, D fixed it

# Of the rescues, how many were missed clearings (FN) vs false alarms (FP)?
resc_fn = rescued & (yte == 1)              # real clearing A missed
resc_fp = rescued & (yte == 0)              # stable land A wrongly flagged

test = df.iloc[te]
def med(mask, col):
    return float(test.loc[mask, col].median())

# Compare the radar/terrain values of rescued pixels vs all test pixels.
# These are the features A does NOT have — if rescued pixels sit at extreme
# values here, that is the measured reason A failed on them.
compare = {}
for col in RADAR + TERRAIN:
    all_med = float(test[col].median())
    resc_med = med(rescued, col)
    compare[col] = {"all_test_median": round(all_med, 3),
                    "rescued_median": round(resc_med, 3),
                    "shift": round(resc_med - all_med, 3)}

summary = {
    "f1_optical_only_A": round(f1A, 4),
    "f1_all_features_D": round(f1D, 4),
    "test_pixels": int(len(te)),
    "A_total_errors": int(A_wrong.sum()),
    "D_rescued_from_A": int(rescued.sum()),
    "rescue_rate_of_A_errors_pct": round(100 * rescued.sum() / A_wrong.sum(), 1),
    "rescued_were_missed_clearings_FN": int(resc_fn.sum()),
    "rescued_were_false_alarms_FP": int(resc_fp.sum()),
    "radar_terrain_value_of_rescued_vs_all": compare,
}

out = HERE / "results" / "metrics" / "lowest_experiment_diagnosis.json"
out.write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))
print(f"\nSaved -> {out}")
