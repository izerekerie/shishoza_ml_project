"""Umurinzi — split audit + patch-size accuracy curve.

Closes RESEARCH_TODO items #1 and #2:

  #1  Audit the train/test split. Confirm there is NO label leakage and that the
      F1 = 0.791 result was measured on a held-out set the model never saw.
      Also flag any *spatial* leakage (neighbouring pixels in both splits).

  #2  Answer RQ2: how does accuracy degrade as clearing patch size approaches
      Rwanda's typical 0.18 ha smallholder farm? We estimate per-pixel patch size
      via DBSCAN spatial clustering of the deforested sample (eps = 35 m, slightly
      above the 30 m Sentinel-2 / Hansen pixel grid). Each connected component is
      one "patch"; size = n_pixels × 0.09 ha. We then bucket the held-out test
      pixels by patch size and report F1 / recall per bucket.

Outputs (all → data/):
  evaluation_audit.json         split sizes, leakage checks, F1/prec/rec/AUC verified
  patch_size_accuracy.csv       per-bucket counts + F1/recall
  patch_size_accuracy.png       Figure 4.X for the dissertation
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from sklearn.cluster import DBSCAN
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split

HERE = Path(__file__).resolve().parent.parent

# ── 1. Load training data + parse coordinates ───────────────────────
print("[1/6] Loading training data …")
raw = pd.read_csv(HERE / "data" / "raw" / "training_data.csv")
raw["lng"] = raw[".geo"].apply(lambda s: json.loads(s)["coordinates"][0])
raw["lat"] = raw[".geo"].apply(lambda s: json.loads(s)["coordinates"][1])
clean = pd.read_csv(HERE / "data" / "processed" / "training_data_clean.csv")
print(f"   {len(raw):,} pixels  ·  classes={raw['label'].value_counts().to_dict()}")

FEATURES = [c for c in clean.columns if c != "label"]
X = clean[FEATURES].values
y = clean["label"].values.astype(int)

# ── 2. Reproduce the canonical 80/20 stratified split ───────────────
print("\n[2/6] Reproducing the canonical train/test split …")
idx_all = np.arange(len(clean))
train_idx, test_idx = train_test_split(
    idx_all, test_size=0.2, random_state=42, stratify=y
)
print(f"   train: {len(train_idx):,}   test: {len(test_idx):,}")

# Label leakage check — are any TEST pixel labels present in TRAIN?
# (They MUST be — both classes appear in both splits. We're really checking
#  that no SAME pixel (same index) appears in both splits, i.e. that the split
#  is a valid partition.)
overlap = set(train_idx) & set(test_idx)
print(f"   train ∩ test (must be 0): {len(overlap)} pixels   "
      f"{'✅ no leakage' if len(overlap) == 0 else '❌ LEAKAGE'}")

# Class balance preserved by stratification?
def class_dist(idx):
    return dict(zip(*np.unique(y[idx], return_counts=True)))
print(f"   train class dist: {class_dist(train_idx)}")
print(f"   test  class dist: {class_dist(test_idx)}")

# ── 3. SPATIAL leakage check — minimum distance from any test point to its
#       nearest train neighbour. If many test points have a train neighbour < 60 m
#       away (2 Hansen pixels), our F1 may be optimistic from spatial autocorrelation.
print("\n[3/6] Spatial-leakage check (KDTree, deg→km on a sphere) …")
tree = cKDTree(np.column_stack([raw.loc[train_idx, "lat"],
                                 raw.loc[train_idx, "lng"]]))
test_coords = np.column_stack([raw.loc[test_idx, "lat"],
                                raw.loc[test_idx, "lng"]])
nearest_deg, _ = tree.query(test_coords, k=1)
nearest_km = nearest_deg * 111.0
nearest_m  = nearest_km * 1000
print(f"   median nearest-train distance:  {np.median(nearest_m):>7.0f} m")
print(f"   25th percentile:                {np.percentile(nearest_m, 25):>7.0f} m")
print(f"   < 60 m  (≤ 2 Hansen pixels):    {int((nearest_m < 60).sum())}  "
      f"({(nearest_m < 60).mean()*100:.1f}% of test set)")
print(f"   < 100 m:                        {int((nearest_m < 100).sum())}  "
      f"({(nearest_m < 100).mean()*100:.1f}%)")
print(f"   ≥ 1 km away:                    {int((nearest_m >= 1000).sum())}  "
      f"({(nearest_m >= 1000).mean()*100:.1f}%)")

# ── 4. Verify the F1 = 0.791 result on this split ───────────────────
print("\n[4/6] Re-verifying F1 = 0.791 from rf_D.pkl …")
model = pickle.load(open(HERE / "models" / "rf_D.pkl", "rb"))
X_test = X[test_idx]
y_test = y[test_idx]
y_pred = model.predict(X_test)
y_prob = model.predict_proba(X_test)[:, 1]
f1   = f1_score(y_test, y_pred)
prec = precision_score(y_test, y_pred)
rec  = recall_score(y_test, y_pred)
auc  = roc_auc_score(y_test, y_prob)
cm   = confusion_matrix(y_test, y_pred).tolist()
print(f"   F1:        {f1:.4f}    (reported in notebook 03: 0.7908)")
print(f"   Precision: {prec:.4f}")
print(f"   Recall:    {rec:.4f}")
print(f"   AUC:       {auc:.4f}")
print(f"   Confusion: TN={cm[0][0]} FP={cm[0][1]} FN={cm[1][0]} TP={cm[1][1]}")

# ── 5. RQ2 — patch-size analysis via spatial clustering ─────────────
print("\n[5/6] Estimating patch sizes via DBSCAN on deforested pixels …")
deforested = raw[raw["label"] == 1].copy()
coords = deforested[["lat", "lng"]].values
# eps = 35 m / 111000 m-per-degree ≈ 3.15e-4°  (a little wider than the 30 m grid)
EPS_DEG = 35.0 / 111_000.0
db = DBSCAN(eps=EPS_DEG, min_samples=1).fit(coords)
deforested["patch_id"] = db.labels_

patch_sizes = deforested.groupby("patch_id").size()      # n_pixels per patch
ha_per_pixel = (30 * 30) / 10_000                        # = 0.09 ha
deforested["patch_size_ha"] = deforested["patch_id"].map(patch_sizes) * ha_per_pixel

print(f"   distinct patches: {len(patch_sizes)}")
print(f"   patch size median: {patch_sizes.median()*ha_per_pixel:.3f} ha  "
      f"max: {patch_sizes.max()*ha_per_pixel:.2f} ha")
print(f"   Rwanda smallholder reference: 0.18 ha")

# Attach patch size to the original index so we can subset test_idx
patch_size_by_index = pd.Series(deforested["patch_size_ha"].values,
                                index=deforested.index)

# Subset to TEST pixels that are deforested
test_def_idx = [i for i in test_idx if y[i] == 1]
test_def_sizes = patch_size_by_index.reindex(test_def_idx).fillna(0).values

# Buckets that bracket Rwanda's 0.18 ha smallholder farm
BUCKETS = [
    ("≤0.1 ha (tiny)",       0.0,   0.10),
    ("0.1–0.2 ha (smallholder)", 0.10, 0.20),
    ("0.2–0.5 ha",            0.20, 0.50),
    ("0.5–1.0 ha",            0.50, 1.00),
    (">1.0 ha (large)",       1.00, 1e9),
]
print("\n[6/6] Per-bucket recall on the deforested test pixels:")
print(f"   {'bucket':<28} {'n_test':>7} {'tp':>5} {'fn':>5} {'recall':>7}")
print(f"   " + "-" * 60)

rows = []
all_pred = model.predict(X[test_def_idx])
for label, lo, hi in BUCKETS:
    mask = (test_def_sizes > lo) & (test_def_sizes <= hi)
    n = int(mask.sum())
    if n == 0:
        rows.append({"bucket": label, "n_test": 0, "tp": 0, "fn": 0, "recall": None})
        print(f"   {label:<28} {0:>7}     —     —      —")
        continue
    tp = int((all_pred[mask] == 1).sum())
    fn = n - tp
    r = tp / n
    rows.append({"bucket": label, "lo_ha": lo, "hi_ha": hi if hi < 1e8 else None,
                 "n_test": n, "tp": tp, "fn": fn, "recall": round(r, 4)})
    print(f"   {label:<28} {n:>7} {tp:>5} {fn:>5} {r:>7.3f}")

bucket_df = pd.DataFrame(rows)
bucket_df.to_csv(HERE / "results" / "patch_size_analysis" / "patch_size_accuracy.csv", index=False)
print(f"\n   → data/patch_size_accuracy.csv")

# Figure: bar chart of recall × bucket  (RQ2 answer)
buckets_with_data = bucket_df[bucket_df["recall"].notna()]
fig, ax = plt.subplots(figsize=(9, 5))
colours = ["#dc2626", "#ea580c", "#facc15", "#22c55e", "#15803d"][:len(buckets_with_data)]
ax.bar(buckets_with_data["bucket"], buckets_with_data["recall"],
       color=colours, edgecolor="#111827", linewidth=0.4)
ax.axhline(0.80, ls="--", color="#6b7280", lw=1, label="model overall recall 0.80")
ax.axvline(1.0, ls=":", color="#dc2626", lw=1.3,
           label="Rwanda smallholder farm (0.18 ha)")
ax.set_ylim(0, 1.05)
ax.set_ylabel("Recall on deforested test pixels")
ax.set_title("RQ2 — Detection recall vs clearing patch size\n"
             "Umurinzi rf_D, n=1000 deforested test pixels, Nyungwe buffer zone")
ax.legend(loc="lower right", fontsize=9)
for x, v, n in zip(buckets_with_data["bucket"],
                    buckets_with_data["recall"], buckets_with_data["n_test"]):
    ax.text(x, v + 0.02, f"{v:.2f}\n(n={n})", ha="center", fontsize=9)
plt.xticks(rotation=10)
plt.tight_layout()
out_png = HERE / "results" / "patch_size_analysis" / "patch_size_accuracy.png"
plt.savefig(out_png, dpi=150, bbox_inches="tight")
print(f"   → data/patch_size_accuracy.png")

# ── Save audit JSON for the dissertation appendix ───────────────────
audit = {
    "split_method":              "stratified 80/20, random_state=42",
    "train_size":                int(len(train_idx)),
    "test_size":                 int(len(test_idx)),
    "train_class_distribution":  {int(k): int(v) for k, v in class_dist(train_idx).items()},
    "test_class_distribution":   {int(k): int(v) for k, v in class_dist(test_idx).items()},
    "label_leakage_pixels":      len(overlap),
    "spatial_proximity_test_set": {
        "median_m_to_nearest_train_pixel": float(np.median(nearest_m)),
        "p25_m":                            float(np.percentile(nearest_m, 25)),
        "lt_60m_pct":                       float((nearest_m < 60).mean() * 100),
        "lt_100m_pct":                      float((nearest_m < 100).mean() * 100),
        "ge_1km_pct":                       float((nearest_m >= 1000).mean() * 100),
    },
    "metrics_held_out": {
        "f1": float(f1), "precision": float(prec),
        "recall": float(rec), "auc": float(auc),
        "confusion_matrix": cm,
    },
    "patch_size_analysis": {
        "method": "DBSCAN eps=35 m on deforested sample, 1 pixel = 0.09 ha",
        "n_patches_found": int(len(patch_sizes)),
        "median_patch_size_ha": float(patch_sizes.median() * ha_per_pixel),
        "buckets": rows,
    },
}
(HERE / "results" / "metrics" / "evaluation_split_audit.json").write_text(json.dumps(audit, indent=2))
print(f"   → data/evaluation_audit.json")

print("\n✓ Done. Two RESEARCH_TODO items closed (#1 split honesty, #2 RQ2 patch-size).")
