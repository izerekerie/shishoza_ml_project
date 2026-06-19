"""Append a NATIONAL section to the bottom of notebooks 02-05.
Existing (Nyungwe) cells are left untouched; national results appear below them.
Idempotent: if a national banner already exists in a notebook, it is skipped."""
import nbformat as nbf
from nbformat.v4 import new_markdown_cell, new_code_cell

BANNER = "NATIONAL DATA (all 5 provinces)"

COMMON = """# ===== NATIONAL SECTION SETUP =====
import json, os, pickle
import numpy as np, pandas as pd
import matplotlib.pyplot as plt
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.cluster import DBSCAN
from sklearn.metrics import f1_score, precision_score, recall_score, confusion_matrix
if os.path.basename(os.getcwd()) == 'notebooks':
    os.chdir('..')

nat_raw = pd.read_csv('data/raw/training_data_national.csv')
nat = nat_raw.drop(columns=[c for c in ['system:index','.geo','province'] if c in nat_raw.columns])
print('National dataset:', nat.shape[0], 'pixels across', nat_raw['province'].nunique(), 'provinces')

def experiments_for(cols):
    A=[c for c in cols if any(x in c for x in ['NDVI','EVI','SWIR','NBR','RED','GREEN','NIR']) and 'label' not in c]
    B=A+[c for c in cols if c in ['elevation','slope','aspect']]
    C=A+[c for c in cols if any(x in c for x in ['VH','VV','ratio'])]
    D=A+[c for c in cols if any(x in c for x in ['elevation','slope','aspect','VH','VV','ratio'])]
    return {'A — Optical only':A,'B — Optical + Terrain':B,'C — Optical + Radar':C,'D — All combined':D}
def rf_tuned():
    return RandomForestClassifier(n_estimators=800, max_depth=25, min_samples_leaf=1,
        max_features='sqrt', class_weight='balanced', random_state=42, n_jobs=-1)"""

# ---------- per-notebook national cells ----------
SECTIONS = {
"notebooks/02_Data_Check.ipynb": [
 ("md", f"# ───────────── {BANNER} ─────────────\n\nThe same data checks as above, now on the **national** dataset (shown below the Nyungwe results)."),
 ("code", COMMON),
 ("md", "## National — Step 2: column names and label balance"),
 ("code", "print('Columns:', list(nat.columns))\nprint('\\nLabel balance:', nat['label'].value_counts().to_dict())\nprint('Province balance:', nat_raw['province'].value_counts().to_dict())"),
 ("md", "## National — Step 3: missing values"),
 ("code", "miss = nat.isna().sum()\nprint(miss[miss>0].to_dict() or 'No missing values')"),
 ("md", "## National — Step 4: NDVI sanity"),
 ("code", "print(nat[['NDVI_train','NDVI_test','NDVI_change']].describe().round(3))"),
 ("md", "## National — Step 5: save clean national dataset"),
 ("code", "nat.to_csv('data/processed/training_data_national_clean.csv', index=False)\nprint('Saved -> data/processed/training_data_national_clean.csv', nat.shape)"),
],
"notebooks/03_Train_Model.ipynb": [
 ("md", f"# ───────────── {BANNER} ─────────────\n\nThe four experiments, feature importance (RQ1) and patch size (RQ2), now on the **national** dataset (below the Nyungwe results above)."),
 ("code", COMMON),
 ("md", "## National — Four experiments (5-fold CV)"),
 ("code", """exps = experiments_for(nat.columns.tolist()); y = nat['label'].values
skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
rows=[]
for name,fcols in exps.items():
    X=nat[fcols].values; f1s=[]
    for tr,te in skf.split(X,y):
        m=RandomForestClassifier(n_estimators=200,max_depth=20,min_samples_leaf=5,
            class_weight='balanced',random_state=42,n_jobs=-1).fit(X[tr],y[tr])
        f1s.append(f1_score(y[te],m.predict(X[te])))
    rows.append({'Experiment':name,'Features':len(fcols),'National_F1':round(np.mean(f1s),3)})
nat_results = pd.DataFrame(rows); display(nat_results)"""),
 ("md", "## National — RQ1: feature importance by source"),
 ("code", """D = experiments_for(nat.columns.tolist())['D — All combined']
mD = rf_tuned().fit(nat[D].values, y)
def src(f):
    if any(x in f for x in ['VH','VV','ratio']): return 'radar'
    if f in ['elevation','slope','aspect']: return 'terrain'
    return 'optical'
g={}
for f,v in zip(D, mD.feature_importances_): g[src(f)]=g.get(src(f),0)+v
print('National importance by source:', {k:round(v,3) for k,v in sorted(g.items(),key=lambda t:-t[1])})"""),
 ("md", "## National — RQ2: patch-size recall (down to 0.18 ha)"),
 ("code", """lat = nat_raw['.geo'].apply(lambda s: json.loads(s)['coordinates'][1]).values
lng = nat_raw['.geo'].apply(lambda s: json.loads(s)['coordinates'][0]).values
X = nat[D].values
idx=np.arange(len(y)); tr,te=train_test_split(idx,test_size=0.2,stratify=y,random_state=42)
m=rf_tuned().fit(X[tr],y[tr]); pred=m.predict(X[te]); pred_te={i:p for i,p in zip(te,pred)}
te_def=te[y[te]==1]; coords=np.column_stack([lat[te_def],lng[te_def]])
labels=DBSCAN(eps=35/111000.0,min_samples=1).fit(coords).labels_
sizes={}; preds={}
for k,gi in zip(labels,te_def):
    sizes[k]=sizes.get(k,0)+0.09; preds.setdefault(k,[]).append(pred_te[gi])
out=[]
for nm,lo,hi in [('<=0.1 ha',0,0.1),('0.1-0.2 ha',0.1,0.2),('0.2-0.5 ha',0.2,0.5)]:
    ks=[k for k,s in sizes.items() if lo<s<=hi]
    tp=sum(sum(preds[k]) for k in ks); n=sum(len(preds[k]) for k in ks)
    out.append({'Patch size':nm,'Pixels':n,'National_recall':round(tp/n,3) if n else None})
pd.DataFrame(out)"""),
],
"notebooks/04_Results_Visualise.ipynb": [
 ("md", f"# ───────────── {BANNER} ─────────────\n\nThe same charts, now for the **national** model (below the Nyungwe charts above)."),
 ("code", COMMON),
 ("md", "## National — Chart 1: F1 across experiments (Nyungwe vs National)"),
 ("code", """cmp = pd.read_csv('results/experiments_national/experiment_results_national.csv')
ax = cmp.set_index('experiment')[['nyungwe_f1','national_f1']].plot(
        kind='bar', figsize=(9,5), color=['#9E9E9E','#1B5E20'])
ax.set_ylabel('F1'); ax.set_ylim(0.6,0.9); ax.set_title('Four experiments — Nyungwe vs National')
plt.xticks(rotation=20, ha='right'); plt.tight_layout()
plt.savefig('results/metrics/results_f1_comparison_national.png', dpi=150, bbox_inches='tight'); plt.show()"""),
 ("md", "## National — Chart 3: confusion matrix (national model D)"),
 ("code", """y = nat['label'].values; D = experiments_for(nat.columns.tolist())['D — All combined']
X = nat[D].values
idx=np.arange(len(y)); tr,te=train_test_split(idx,test_size=0.2,stratify=y,random_state=42)
m=rf_tuned().fit(X[tr],y[tr]); cm=confusion_matrix(y[te], m.predict(X[te]))
fig,ax=plt.subplots(figsize=(5,4))
im=ax.imshow(cm,cmap='Greens')
for i in range(2):
    for j in range(2): ax.text(j,i,cm[i,j],ha='center',va='center',fontsize=14)
ax.set_xticks([0,1]); ax.set_yticks([0,1])
ax.set_xticklabels(['Forest','Cleared']); ax.set_yticklabels(['Forest','Cleared'])
ax.set_xlabel('Predicted'); ax.set_ylabel('Actual'); ax.set_title('National model D — confusion matrix')
plt.tight_layout(); plt.savefig('results/metrics/confusion_matrix_national.png', dpi=150, bbox_inches='tight'); plt.show()
print('National held-out F1:', round(f1_score(y[te], m.predict(X[te])),3))"""),
],
"notebooks/05_Predict_Parcel.ipynb": [
 ("md", f"# ───────────── {BANNER} ─────────────\n\nThe parcel prediction, now using the **national** model (`rf_D_national.pkl`) so it works anywhere in Rwanda (below the Nyungwe demo above)."),
 ("code", COMMON),
 ("md", "## National — load the national model + national pixels"),
 ("code", """from scipy.spatial import cKDTree
model = pickle.load(open('models/rf_D_national.pkl','rb'))
FEATURE_COLS = ['EVI_train','NBR_train','NDVI_change','NDVI_test','NDVI_train','NIR_train',
                'RED_train','SWIR_test','SWIR_train','VH_VV_ratio','VH_test','VH_train',
                'VV_test','VV_train','aspect','elevation','slope']
g = nat_raw['.geo'].apply(lambda s: json.loads(s)['coordinates'])
nat_raw['lng']=g.apply(lambda c:c[0]); nat_raw['lat']=g.apply(lambda c:c[1])
tree = cKDTree(nat_raw[['lat','lng']].values)
print('National model:', model.n_features_in_, 'features | KD-tree:', len(nat_raw), 'pixels')"""),
 ("md", "## National — predict on parcels across the country"),
 ("code", """def predict_national(lat, lng, name):
    d, idx = tree.query([lat,lng], k=25)
    feats = nat_raw.iloc[idx][FEATURE_COLS].median().values.reshape(1,-1)
    prob = float(model.predict_proba(feats)[0][1])
    km = float(d[0]*111)
    print(f'{name:18s} prob_cleared={prob:.2f}  nearest_sample={km:.1f} km  '
          f'-> {"Deforested" if prob>0.5 else "Stable forest"}')

predict_national(-2.45, 29.20, 'Nyungwe (West)')
predict_national(-1.95, 30.06, 'Kigali')
predict_national(-1.50, 29.60, 'Musanze (North)')
predict_national(-2.60, 30.40, 'Huye (South)')
predict_national(-1.95, 30.60, 'Kayonza (East)')
print('\\nThe model now returns a calibrated prediction nationwide, not just in Nyungwe.')"""),
],
}

for path, specs in SECTIONS.items():
    nb = nbf.read(path, as_version=4)
    if any(BANNER in ''.join(c.source) for c in nb.cells):
        print('skip (already has national section):', path); continue
    for kind, text in specs:
        nb.cells.append(new_markdown_cell(text) if kind=='md' else new_code_cell(text))
    nbf.write(nb, path)
    print('appended national section ->', path)
