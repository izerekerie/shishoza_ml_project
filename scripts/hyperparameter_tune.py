"""TreeSight — Hyperparameter tuning for Random Forest Experiment D.

Closes the "Model architecture" gap on the ML Track rubric by replacing the
unjustified defaults (n_estimators=400, max_depth=15) with grid-searched
choices backed by 5-fold cross-validation.

Grid (48 combinations × 5 folds = 240 fits):
    n_estimators     ∈ {100, 200, 400, 800}
    max_depth        ∈ {None, 10, 15, 25}
    min_samples_leaf ∈ {1, 2, 5}
    max_features     ∈ {'sqrt', 'log2'}

Output:
    data/hp_tuning_results.csv     – every combination with mean+std F1
    data/hp_tuning_heatmap.png      – n_estimators × max_depth F1 heat-map
    data/hp_tuning_summary.json     – best params + comparison vs current model
    models/rf_D_tuned.pkl           – retrained best model (saved separately so
                                     rf_D.pkl baseline is preserved)

Run:  .venv/bin/python scripts/hyperparameter_tune.py
"""

from __future__ import annotations

import json
import pickle
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import GridSearchCV, train_test_split

HERE = Path(__file__).resolve().parent.parent

# ── 1. Load training data ────────────────────────────────────────────
print("[1/6] Loading training data …")
df = pd.read_csv(HERE / "data" / "processed" / "training_data_clean.csv")
FEATURES = [c for c in df.columns if c != "label"]
X = df[FEATURES].values
y = df["label"].values
print(f"  {len(df):,} pixels, {len(FEATURES)} features, "
      f"classes={pd.Series(y).value_counts().to_dict()}")

# Same 80/20 stratified split as notebook 03 — keeps the comparison honest
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)

# ── 2. Define the grid ───────────────────────────────────────────────
print("\n[2/6] Defining grid (48 combinations × 5-fold CV = 240 fits) …")
param_grid = {
    "n_estimators":     [100, 200, 400, 800],
    "max_depth":        [None, 10, 15, 25],
    "min_samples_leaf": [1, 2, 5],
    "max_features":     ["sqrt", "log2"],
}
n_combos = (len(param_grid["n_estimators"]) * len(param_grid["max_depth"])
            * len(param_grid["min_samples_leaf"]) * len(param_grid["max_features"]))
print(f"  Total combinations: {n_combos}")

# ── 3. Run GridSearchCV ─────────────────────────────────────────────
print("\n[3/6] Running GridSearchCV with 5-fold cross-validation …")
print("  (~10-15 min on CPU; progress markers below)")
base = RandomForestClassifier(class_weight="balanced", random_state=42, n_jobs=-1)
gs = GridSearchCV(
    estimator=base,
    param_grid=param_grid,
    scoring="f1",
    cv=5,
    n_jobs=-1,
    verbose=1,
    return_train_score=True,
)
t0 = time.time()
gs.fit(X_train, y_train)
dt = time.time() - t0
print(f"\n  Search finished in {dt:.1f} s ({dt/60:.1f} min)")

# ── 4. Compute test-set metrics for the best model ──────────────────
print("\n[4/6] Evaluating best model on held-out test set …")
best = gs.best_estimator_
y_pred = best.predict(X_test)
y_proba = best.predict_proba(X_test)[:, 1]
new_f1 = f1_score(y_test, y_pred)
new_prec = precision_score(y_test, y_pred)
new_rec = recall_score(y_test, y_pred)
new_auc = roc_auc_score(y_test, y_proba)

# Compare with the current baseline (rf_D.pkl)
baseline_model = pickle.load(open(HERE / "models" / "rf_D.pkl", "rb"))
base_pred = baseline_model.predict(X_test)
base_proba = baseline_model.predict_proba(X_test)[:, 1]
base_f1 = f1_score(y_test, base_pred)
base_prec = precision_score(y_test, base_pred)
base_rec = recall_score(y_test, base_pred)
base_auc = roc_auc_score(y_test, base_proba)

print()
print(f"{'Metric':<12} {'Baseline (rf_D)':<18} {'Tuned (rf_D_tuned)':<20} {'Δ':>8}")
print("-" * 60)
for name, b, n in [
    ("F1",        base_f1,   new_f1),
    ("Precision", base_prec, new_prec),
    ("Recall",    base_rec,  new_rec),
    ("AUC",       base_auc,  new_auc),
]:
    delta = n - b
    print(f"{name:<12} {b:<18.4f} {n:<20.4f} {delta:>+8.4f}")
print()
print(f"Best hyperparameters: {gs.best_params_}")
print(f"Best CV F1:           {gs.best_score_:.4f}")

# ── 5. Save full grid results + heatmap ─────────────────────────────
print("\n[5/6] Saving grid results …")
out_dir = HERE / "data"
results_df = pd.DataFrame(gs.cv_results_)
keep_cols = [c for c in results_df.columns
             if c.startswith("param_")] + ["mean_test_score", "std_test_score",
                                            "mean_fit_time", "rank_test_score"]
results_df[keep_cols].sort_values("rank_test_score").to_csv(
    out_dir / "hp_tuning_results.csv", index=False
)
print(f"  → {out_dir / 'hp_tuning_results.csv'}")

# Heatmap: mean F1 across (n_estimators × max_depth), averaged over the
# other two axes. This is the figure for the dissertation.
pivot = results_df.assign(
    param_max_depth=results_df["param_max_depth"].astype(str)
).pivot_table(
    values="mean_test_score",
    index="param_n_estimators",
    columns="param_max_depth",
    aggfunc="mean",
)
fig, ax = plt.subplots(figsize=(8, 5))
sns.heatmap(pivot, annot=True, fmt=".4f", cmap="viridis", ax=ax,
            cbar_kws={"label": "Mean CV F1-score"})
ax.set_title("Random Forest hyperparameter grid — mean CV F1\n"
             "Averaged over min_samples_leaf and max_features")
ax.set_xlabel("max_depth")
ax.set_ylabel("n_estimators")
plt.tight_layout()
plt.savefig(out_dir / "hp_tuning_heatmap.png", dpi=150, bbox_inches="tight")
print(f"  → {out_dir / 'hp_tuning_heatmap.png'}")

# ── 6. Save the retrained best model + summary JSON ─────────────────
print("\n[6/6] Saving tuned model + summary …")
pickle.dump(best, open(HERE / "models" / "rf_D_tuned.pkl", "wb"))
print(f"  → models/rf_D_tuned.pkl")

summary = {
    "model_version":         "rf_D_tuned_v1.0.0",
    "trained_at":            "2026-06-10",
    "search_seconds":        round(dt, 1),
    "search_combinations":   n_combos,
    "cv_folds":              5,
    "total_fits":            n_combos * 5,
    "best_params":           {k: v for k, v in gs.best_params_.items()},
    "best_cv_f1":            float(gs.best_score_),
    "best_cv_f1_std":        float(
        results_df.loc[results_df["rank_test_score"] == 1, "std_test_score"].iloc[0]
    ),
    "test_metrics_baseline": {
        "f1":        float(base_f1),
        "precision": float(base_prec),
        "recall":    float(base_rec),
        "auc":       float(base_auc),
    },
    "test_metrics_tuned": {
        "f1":        float(new_f1),
        "precision": float(new_prec),
        "recall":    float(new_rec),
        "auc":       float(new_auc),
    },
    "delta_vs_baseline": {
        "f1":        float(new_f1 - base_f1),
        "precision": float(new_prec - base_prec),
        "recall":    float(new_rec - base_rec),
        "auc":       float(new_auc - base_auc),
    },
}
(out_dir / "hp_tuning_summary.json").write_text(json.dumps(summary, indent=2))
print(f"  → {out_dir / 'hp_tuning_summary.json'}")

print("\n✓ Done. The dissertation can now cite:")
print(f"    'A grid-search over {n_combos} combinations with 5-fold CV")
print(f"     identified best parameters: {gs.best_params_}")
print(f"     achieving F1 = {new_f1:.4f} (Δ {new_f1-base_f1:+.4f} vs default).'")
