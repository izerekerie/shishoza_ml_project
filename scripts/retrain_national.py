"""Retrain on the NATIONAL dataset and compare to Nyungwe-only.
Saves everything with a _national suffix so existing results are NOT overwritten.

Three comparisons:
  1. Four experiments (A/B/C/D), 5-fold random CV — national vs Nyungwe (same protocol, n=200 trees)
  2. National spatial block CV (tuned RF, 800 trees) — honest generalization number
  3. Leave-one-province-out CV — does national training generalize across regions?
"""
import json, os, numpy as np, pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.cluster import KMeans
from sklearn.model_selection import StratifiedKFold, GroupKFold
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score
import pickle

os.makedirs('results/experiments_national', exist_ok=True)
os.makedirs('results/metrics', exist_ok=True)

def experiments_for(cols):
    exp_A = [c for c in cols if any(x in c for x in
             ['NDVI','EVI','SWIR','NBR','RED','GREEN','NIR']) and 'label' not in c]
    exp_B = exp_A + [c for c in cols if c in ['elevation','slope','aspect']]
    exp_C = exp_A + [c for c in cols if any(x in c for x in ['VH','VV','ratio'])]
    exp_D = exp_A + [c for c in cols if any(x in c for x in
             ['elevation','slope','aspect','VH','VV','ratio'])]
    return {'A — Optical only':exp_A, 'B — Optical + Terrain':exp_B,
            'C — Optical + Radar':exp_C, 'D — All combined':exp_D}

def rf200():  # matches the original 4-experiment protocol
    return RandomForestClassifier(n_estimators=200, max_depth=20, min_samples_leaf=5,
        class_weight='balanced', random_state=42, n_jobs=-1)
def rf_tuned():  # matches the spatial-CV protocol used for Nyungwe
    return RandomForestClassifier(n_estimators=800, max_depth=25, min_samples_leaf=1,
        max_features='sqrt', class_weight='balanced', random_state=42, n_jobs=-1)

def cv_experiments(df, label_col='label'):
    cols = df.columns.tolist()
    exps = experiments_for(cols)
    y = df[label_col].values
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    out = {}
    for name, fcols in exps.items():
        X = df[fcols].values
        f1s=[]
        for tr,te in skf.split(X,y):
            m=rf200().fit(X[tr],y[tr]); f1s.append(f1_score(y[te],m.predict(X[te])))
        out[name] = (len(fcols), float(np.mean(f1s)), float(np.std(f1s)))
    return out

# ── load ────────────────────────────────────────────────────────────
nat_raw = pd.read_csv('data/raw/training_data_national.csv')
drop = [c for c in ['system:index','.geo','province'] if c in nat_raw.columns]
nat = nat_raw.drop(columns=drop)
nyu = pd.read_csv('data/processed/training_data_clean.csv')
print(f'National: {nat.shape[0]} pixels | Nyungwe: {nyu.shape[0]} pixels\n')

# ── 1. FOUR EXPERIMENTS, fair 5-fold CV, both datasets ───────────────
print('[1/3] Four experiments (5-fold CV, 200 trees) ...')
nat_exp = cv_experiments(nat)
nyu_exp = cv_experiments(nyu)
print(f'\n{"Experiment":22s} {"Nyungwe F1":>12s} {"National F1":>12s} {"Δ":>8s}')
rows=[]
for name in nat_exp:
    nf, nmean, nstd = nyu_exp[name]
    _, amean, astd = nat_exp[name]
    print(f'{name:22s} {nmean:>12.3f} {amean:>12.3f} {amean-nmean:>+8.3f}')
    rows.append({'experiment':name,'n_features':nf,
                 'nyungwe_f1':round(nmean,4),'nyungwe_std':round(nstd,4),
                 'national_f1':round(amean,4),'national_std':round(astd,4),
                 'delta':round(amean-nmean,4)})
pd.DataFrame(rows).to_csv('results/experiments_national/experiment_results_national.csv', index=False)

# ── 2. NATIONAL spatial block CV (tuned) ─────────────────────────────
print('\n[2/3] National spatial block CV (800 trees) ...')
lng = nat_raw['.geo'].apply(lambda s: json.loads(s)['coordinates'][0]).values
lat = nat_raw['.geo'].apply(lambda s: json.loads(s)['coordinates'][1]).values
expD = experiments_for(nat.columns.tolist())['D — All combined']
Xd = nat[expD].values; y = nat['label'].values
blocks = KMeans(n_clusters=10, random_state=42, n_init=10).fit_predict(np.column_stack([lat,lng]))
gkf=GroupKFold(n_splits=5); sf1=[]
for tr,te in gkf.split(Xd,y,groups=blocks):
    m=rf_tuned().fit(Xd[tr],y[tr]); sf1.append(f1_score(y[te],m.predict(Xd[te])))
print(f'   National spatial-CV F1 = {np.mean(sf1):.3f} +/- {np.std(sf1):.3f}')

# ── 3. LEAVE-ONE-PROVINCE-OUT (generalization across regions) ────────
print('\n[3/3] Leave-one-province-out CV (does it generalize?) ...')
prov = nat_raw['province'].values
lopo={}
for p in pd.unique(prov):
    tr = prov!=p; te = prov==p
    if te.sum()<50: continue
    m=rf_tuned().fit(Xd[tr],y[tr]); pred=m.predict(Xd[te])
    lopo[p]={'n_test':int(te.sum()),'f1':round(float(f1_score(y[te],pred)),4),
             'recall':round(float(recall_score(y[te],pred)),4)}
    print(f'   hold out {p:32s} -> F1 = {lopo[p]["f1"]:.3f}  (n={lopo[p]["n_test"]})')

# ── train + save the 4 national models on full data ──────────────────
print('\nSaving national models ...')
exps = experiments_for(nat.columns.tolist())
tags={'A — Optical only':'A','B — Optical + Terrain':'B','C — Optical + Radar':'C','D — All combined':'D'}
for name,fcols in exps.items():
    m=rf_tuned().fit(nat[fcols].values, y)
    with open(f'models/rf_{tags[name]}_national.pkl','wb') as f: pickle.dump(m,f)
print('   models/rf_A_national.pkl ... rf_D_national.pkl')

# ── save metrics json ────────────────────────────────────────────────
out={'dataset_sizes':{'national':int(nat.shape[0]),'nyungwe':int(nyu.shape[0])},
     'four_experiments_5foldcv_200trees':rows,
     'national_spatial_block_cv':{'method':'KMeans 10 blocks, GroupKFold-5, 800 trees',
        'f1':round(float(np.mean(sf1)),4),'f1_std':round(float(np.std(sf1)),4),
        'per_fold':[round(float(x),4) for x in sf1]},
     'leave_one_province_out':lopo}
json.dump(out, open('results/metrics/national_comparison.json','w'), indent=2)
print('\nSaved -> results/metrics/national_comparison.json')
print('Saved -> results/experiments_national/experiment_results_national.csv')
