"""Answer RQ1 (feature importance) and RQ2 (patch-size recall) on the NATIONAL data.
Saves with _national names; nothing existing is overwritten."""
import json, os, numpy as np, pandas as pd, pickle
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.cluster import DBSCAN
from sklearn.metrics import f1_score, recall_score, precision_score

os.makedirs('results/experiments_national', exist_ok=True)
os.makedirs('results/patch_size_analysis_national', exist_ok=True)

raw = pd.read_csv('data/raw/training_data_national.csv')
df  = raw.drop(columns=[c for c in ['system:index','.geo','province'] if c in raw.columns])
cols = df.columns.tolist()
exp_A = [c for c in cols if any(x in c for x in ['NDVI','EVI','SWIR','NBR','RED','GREEN','NIR']) and 'label' not in c]
exp_D = exp_A + [c for c in cols if any(x in c for x in ['elevation','slope','aspect','VH','VV','ratio'])]
y = df['label'].values

# ── RQ1: feature importance from the national D model ────────────────
print('[RQ1] Feature importance (national, model D) ...')
with open('models/rf_D_national.pkl','rb') as f:
    modelD = pickle.load(f)
imp = sorted(zip(exp_D, modelD.feature_importances_), key=lambda t:-t[1])
fi_rows = [{'feature':f,'importance':round(float(v),4)} for f,v in imp]
pd.DataFrame(fi_rows).to_csv('results/experiments_national/feature_importance_national.csv', index=False)
print('   Top 8 features (national):')
for f,v in imp[:8]:
    print(f'      {f:14s} {v:.3f}')
# group by source
def src(f):
    if any(x in f for x in ['VH','VV','ratio']): return 'radar'
    if f in ['elevation','slope','aspect']:      return 'terrain'
    return 'optical'
grp={}
for f,v in imp: grp[src(f)]=grp.get(src(f),0)+v
print('   By source:', {k:round(v,3) for k,v in sorted(grp.items(), key=lambda t:-t[1])})

# ── RQ2: patch-size recall on a held-out national split ──────────────
print('\n[RQ2] Patch-size recall (national, model D) ...')
lng = raw['.geo'].apply(lambda s: json.loads(s)['coordinates'][0]).values
lat = raw['.geo'].apply(lambda s: json.loads(s)['coordinates'][1]).values
Xd = df[exp_D].values
idx = np.arange(len(y))
tr, te = train_test_split(idx, test_size=0.2, stratify=y, random_state=42)
m = RandomForestClassifier(n_estimators=800, max_depth=25, min_samples_leaf=1,
        max_features='sqrt', class_weight='balanced', random_state=42, n_jobs=-1).fit(Xd[tr], y[tr])
pred = m.predict(Xd[te])

# cluster the truly-deforested TEST pixels into patches (same method as Nyungwe eval)
EPS_DEG = 35/111000.0   # ~35 m
te_def = te[y[te]==1]
coords = np.column_stack([lat[te_def], lng[te_def]])
labels = DBSCAN(eps=EPS_DEG, min_samples=1).fit(coords).labels_
PIX_HA = 0.09
# per patch: size + whether caught (recall over its pixels)
patch_sizes = {}
patch_pred  = {}
pred_for_te = {i:p for i,p in zip(te, pred)}
for k, gi in zip(labels, te_def):
    patch_sizes[k] = patch_sizes.get(k,0)+PIX_HA
    patch_pred.setdefault(k,[]).append(pred_for_te[gi])
buckets=[('<=0.1 ha',0,0.1),('0.1-0.2 ha',0.1,0.2),('0.2-0.5 ha',0.2,0.5),
         ('0.5-1.0 ha',0.5,1.0),('>1.0 ha',1.0,1e9)]
rows=[]
for name,lo,hi in buckets:
    ks=[k for k,s in patch_sizes.items() if lo<s<=hi]
    tp=sum(sum(patch_pred[k]) for k in ks)
    n =sum(len(patch_pred[k]) for k in ks)
    rec = tp/n if n else None
    rows.append({'bucket':name,'n_patches':len(ks),'n_pixels':n,
                 'recall':round(rec,4) if rec is not None else None})
    if n: print(f'   {name:12s} patches={len(ks):4d} pixels={n:5d} recall={rec:.3f}')
pd.DataFrame(rows).to_csv('results/patch_size_analysis_national/patch_size_national.csv', index=False)

# overall held-out metrics on national
overall={'f1':round(float(f1_score(y[te],pred)),4),
         'precision':round(float(precision_score(y[te],pred)),4),
         'recall':round(float(recall_score(y[te],pred)),4)}
print('\n   National held-out (D):', overall)

json.dump({'feature_importance':fi_rows,'by_source':{k:round(v,4) for k,v in grp.items()},
           'patch_size':rows,'held_out_D':overall},
          open('results/metrics/national_rq_analysis.json','w'), indent=2)
print('\nSaved -> results/metrics/national_rq_analysis.json')
print('Saved -> results/experiments_national/feature_importance_national.csv')
print('Saved -> results/patch_size_analysis_national/patch_size_national.csv')
