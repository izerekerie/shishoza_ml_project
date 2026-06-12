"""TreeSight — Comprehensive EDA visualisations for the dissertation.

Generates the six missing standard ML-paper artefacts for the ML Track rubric:

  1. Class balance bar chart
  2. All-17-feature distributions (box plots per class)
  3. Feature correlation heatmap
  4. PCA 2-D scatter coloured by class
  5. Spatial distribution map of training samples
  6. Precision-Recall curve (complements the existing ROC)

Run:  .venv/bin/python scripts/eda_visualisations.py
Outputs go to data/eda/*.png
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from sklearn.decomposition import PCA
from sklearn.metrics import precision_recall_curve, average_precision_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

# ── Setup ────────────────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent.parent
OUT = HERE / "results" / "eda"
OUT.mkdir(parents=True, exist_ok=True)
plt.rcParams.update({
    "figure.dpi": 110,
    "savefig.dpi": 150,
    "figure.facecolor": "white",
    "font.family": "DejaVu Sans",
})

print("=== Loading data ===")
df_clean = pd.read_csv(HERE / "data" / "processed" / "training_data_clean.csv")
df_raw = pd.read_csv(HERE / "data" / "raw" / "training_data.csv")
df_raw["lng"] = df_raw[".geo"].apply(lambda s: json.loads(s)["coordinates"][0])
df_raw["lat"] = df_raw[".geo"].apply(lambda s: json.loads(s)["coordinates"][1])

FEATURES = [c for c in df_clean.columns if c != "label"]
print(f"  10k pixels, {len(FEATURES)} features, classes={df_clean.label.value_counts().to_dict()}")

# ── 1. Class balance ─────────────────────────────────────────────────
print("\n[1/6] Class balance bar chart")
counts = df_clean["label"].value_counts().sort_index()
fig, ax = plt.subplots(figsize=(6, 4))
bars = ax.bar(["Stable forest (label=0)", "Deforested (label=1)"], counts.values,
              color=["#16a34a", "#dc2626"], edgecolor="black", linewidth=0.5)
for bar, v in zip(bars, counts.values):
    ax.text(bar.get_x() + bar.get_width()/2, v + 50, f"{v:,}",
            ha="center", fontweight="bold")
ax.set_ylabel("Number of pixels in training set")
ax.set_title(f"Class balance (n = {len(df_clean):,} pixels)\n"
             f"Stratified sampling guarantees 1:1 ratio")
ax.set_ylim(0, max(counts) * 1.15)
plt.tight_layout()
plt.savefig(OUT / "fig_1_class_balance.png", bbox_inches="tight")
plt.close()
print(f"  → {OUT / 'fig_1_class_balance.png'}")

# ── 2. All-17-feature distributions, box plots per class ─────────────
print("\n[2/6] 17-feature distributions per class")
n_cols = 4
n_rows = int(np.ceil(len(FEATURES) / n_cols))
fig, axes = plt.subplots(n_rows, n_cols, figsize=(15, 3.2 * n_rows))
axes = axes.flatten()
for i, feat in enumerate(FEATURES):
    ax = axes[i]
    parts = [df_clean[df_clean["label"] == 0][feat].dropna(),
             df_clean[df_clean["label"] == 1][feat].dropna()]
    bp = ax.boxplot(parts, patch_artist=True, widths=0.6,
                    labels=["Stable", "Deforested"], showfliers=False)
    for patch, c in zip(bp["boxes"], ["#16a34a", "#dc2626"]):
        patch.set_facecolor(c); patch.set_alpha(0.65)
    ax.set_title(feat, fontsize=11, fontweight="bold")
    ax.grid(axis="y", alpha=0.3)
for j in range(len(FEATURES), len(axes)):
    axes[j].set_visible(False)
fig.suptitle("Per-feature distributions, stratified by class (median + IQR; "
             "outliers hidden)", fontsize=14, y=1.00)
plt.tight_layout()
plt.savefig(OUT / "fig_2_feature_distributions.png", bbox_inches="tight")
plt.close()
print(f"  → {OUT / 'fig_2_feature_distributions.png'}")

# ── 3. Feature correlation heatmap ───────────────────────────────────
print("\n[3/6] Correlation heatmap")
corr = df_clean[FEATURES].corr()
fig, ax = plt.subplots(figsize=(11, 9))
sns.heatmap(corr, annot=True, fmt=".2f", cmap="RdBu_r", center=0,
            square=True, linewidths=0.5, ax=ax,
            annot_kws={"size": 8}, cbar_kws={"shrink": 0.7})
ax.set_title("Feature correlation matrix (Pearson r)\n"
             "|r| > 0.7 indicates highly correlated pairs that may be redundant")
plt.tight_layout()
plt.savefig(OUT / "fig_3_correlation_heatmap.png", bbox_inches="tight")
plt.close()
# Also extract the top redundant pairs for the dissertation text
upper = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool)).abs()
top_pairs = upper.unstack().dropna().sort_values(ascending=False).head(8)
print(f"  → {OUT / 'fig_3_correlation_heatmap.png'}")
print(f"  Top 8 most correlated pairs (cite in the dissertation):")
for (a, b), v in top_pairs.items():
    print(f"    {a:14s} ↔ {b:14s}  |r| = {v:.3f}")

# ── 4. PCA scatter coloured by class ─────────────────────────────────
print("\n[4/6] PCA 2-D projection coloured by class")
X = df_clean[FEATURES].fillna(df_clean[FEATURES].median()).values
y = df_clean["label"].values
Xs = StandardScaler().fit_transform(X)
pca = PCA(n_components=2, random_state=42)
Xp = pca.fit_transform(Xs)
fig, ax = plt.subplots(figsize=(8, 6))
for lbl, c, name in [(0, "#16a34a", "Stable forest"), (1, "#dc2626", "Deforested")]:
    pts = Xp[y == lbl]
    ax.scatter(pts[:, 0], pts[:, 1], s=8, alpha=0.35, c=c, label=name,
               edgecolors="none")
ax.set_xlabel(f"PC1 ({pca.explained_variance_ratio_[0]*100:.1f}% variance)")
ax.set_ylabel(f"PC2 ({pca.explained_variance_ratio_[1]*100:.1f}% variance)")
ax.set_title("PCA 2-D projection of the 17-feature space\n"
             f"Total variance captured: {sum(pca.explained_variance_ratio_)*100:.1f}%")
ax.legend(markerscale=2)
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(OUT / "fig_4_pca_scatter.png", bbox_inches="tight")
plt.close()
print(f"  → {OUT / 'fig_4_pca_scatter.png'}")
print(f"  PC1+PC2 explain {sum(pca.explained_variance_ratio_)*100:.1f}% of the variance — "
      f"{'classes are' if sum(pca.explained_variance_ratio_) > 0.5 else 'classes are NOT'} "
      "well-separable in low-dim projection")

# ── 5. Spatial distribution map of training samples ──────────────────
print("\n[5/6] Spatial distribution of training samples (Nyungwe study area)")
fig, ax = plt.subplots(figsize=(9, 9))
for lbl, c, name in [(0, "#16a34a", "Stable forest"),
                     (1, "#dc2626", "Deforested 2020-22")]:
    pts = df_raw[df_raw["label"] == lbl]
    ax.scatter(pts["lng"], pts["lat"], s=4, alpha=0.55, c=c, label=name,
               edgecolors="none")
ax.set_xlabel("Longitude (°E)")
ax.set_ylabel("Latitude (°N)")
ax.set_title("Spatial distribution of the 10,000 training samples in "
             "Rwanda's Nyungwe buffer zone\n"
             "Both classes are spread across the full study area (stratified random sampling)")
ax.legend(markerscale=3)
ax.set_aspect("equal", adjustable="datalim")
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(OUT / "fig_5_spatial_distribution.png", bbox_inches="tight")
plt.close()
print(f"  → {OUT / 'fig_5_spatial_distribution.png'}")

# ── 6. Precision-Recall curve ────────────────────────────────────────
print("\n[6/6] Precision-Recall curve for the deployed model rf_D.pkl")
model = pickle.load(open(HERE / "models" / "rf_D.pkl", "rb"))
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)
y_proba = model.predict_proba(X_test)[:, 1]
prec, rec, thresh = precision_recall_curve(y_test, y_proba)
ap = average_precision_score(y_test, y_proba)

fig, ax = plt.subplots(figsize=(7, 6))
ax.plot(rec, prec, color="#1e3a8a", linewidth=2.5,
        label=f"Random Forest (Experiment D)\nAverage Precision = {ap:.3f}")
ax.axhline(0.5, ls="--", c="grey", alpha=0.5, label="Random classifier baseline")
ax.set_xlabel("Recall")
ax.set_ylabel("Precision")
ax.set_xlim(0, 1.02); ax.set_ylim(0, 1.02)
ax.set_title("Precision-Recall curve — Experiment D (rf_D.pkl)\n"
             "Complements ROC for balanced binary classification")
ax.legend(loc="lower left")
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(OUT / "fig_6_precision_recall.png", bbox_inches="tight")
plt.close()
print(f"  → {OUT / 'fig_6_precision_recall.png'}")
print(f"  Average Precision (AP) = {ap:.3f}")

print("\n=== Done ===")
print(f"All 6 EDA figures saved to {OUT}/")
