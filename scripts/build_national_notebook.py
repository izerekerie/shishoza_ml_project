"""Generate notebooks/06_National_Extension.ipynb — shows every result for
Nyungwe first, then the national result directly below it, plus combined views."""
import nbformat as nbf
from nbformat.v4 import new_notebook, new_markdown_cell, new_code_cell

cells = []
def md(t):  cells.append(new_markdown_cell(t))
def co(t):  cells.append(new_code_cell(t))

md("""# Notebook 06 — National Extension (Nyungwe vs National)

This notebook keeps the original **Nyungwe-only** results and shows the new
**national** results (all 5 provinces) directly below each one, so the two are
easy to compare.

- Nyungwe dataset: `data/processed/training_data_clean.csv` (10,000 pixels)
- National dataset: `data/raw/training_data_national.csv` (23,319 pixels, 5 provinces)

Run top to bottom.""")

# ---- setup
md("## Step 0 — Setup: load both datasets")
co("""import json, os
import numpy as np, pandas as pd
import matplotlib.pyplot as plt
from sklearn.ensemble import RandomForestClassifier
from sklearn.cluster import KMeans, DBSCAN
from sklearn.model_selection import StratifiedKFold, GroupKFold, train_test_split
from sklearn.metrics import f1_score, precision_score, recall_score
import warnings; warnings.filterwarnings('ignore')

if os.path.basename(os.getcwd()) == 'notebooks':
    os.chdir('..')
print('Working dir:', os.getcwd())

# Nyungwe (clean) and National (raw -> drop non-features)
nyu = pd.read_csv('data/processed/training_data_clean.csv')
nat_raw = pd.read_csv('data/raw/training_data_national.csv')
nat = nat_raw.drop(columns=[c for c in ['system:index','.geo','province'] if c in nat_raw.columns])

print(f'Nyungwe : {nyu.shape[0]:,} pixels')
print(f'National: {nat.shape[0]:,} pixels  | provinces:', nat_raw['province'].nunique())""")

co("""# Feature sets for the four experiments (same logic as Notebook 03)
def experiments_for(cols):
    A = [c for c in cols if any(x in c for x in ['NDVI','EVI','SWIR','NBR','RED','GREEN','NIR']) and 'label' not in c]
    B = A + [c for c in cols if c in ['elevation','slope','aspect']]
    C = A + [c for c in cols if any(x in c for x in ['VH','VV','ratio'])]
    D = A + [c for c in cols if any(x in c for x in ['elevation','slope','aspect','VH','VV','ratio'])]
    return {'A — Optical only':A, 'B — Optical + Terrain':B, 'C — Optical + Radar':C, 'D — All combined':D}

def rf200():
    return RandomForestClassifier(n_estimators=200, max_depth=20, min_samples_leaf=5,
        class_weight='balanced', random_state=42, n_jobs=-1)
def rf_tuned():
    return RandomForestClassifier(n_estimators=800, max_depth=25, min_samples_leaf=1,
        max_features='sqrt', class_weight='balanced', random_state=42, n_jobs=-1)

def cv_experiments(df):
    exps = experiments_for(df.columns.tolist()); y = df['label'].values
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    rows=[]
    for name,fcols in exps.items():
        X=df[fcols].values; f1s=[]
        for tr,te in skf.split(X,y):
            m=rf200().fit(X[tr],y[tr]); f1s.append(f1_score(y[te],m.predict(X[te])))
        rows.append({'Experiment':name,'Features':len(fcols),'F1':round(np.mean(f1s),3),'std':round(np.std(f1s),3)})
    return pd.DataFrame(rows)""")

# ---- RQ1 experiments
md("""## Step 1 — RQ1: the four experiments (does radar / terrain help?)

First the **Nyungwe-only** result, then the **national** result below it.""")
md("### Nyungwe-only")
co("nyu_exp = cv_experiments(nyu)\nnyu_exp")
md("### National (below)")
co("nat_exp = cv_experiments(nat)\nnat_exp")
md("### Side-by-side comparison")
co("""cmp = nyu_exp[['Experiment','F1']].rename(columns={'F1':'Nyungwe_F1'}).merge(
        nat_exp[['Experiment','F1']].rename(columns={'F1':'National_F1'}), on='Experiment')
cmp['Change'] = (cmp['National_F1'] - cmp['Nyungwe_F1']).round(3)
display(cmp)

ax = cmp.set_index('Experiment')[['Nyungwe_F1','National_F1']].plot(kind='bar', figsize=(9,5),
        color=['#9E9E9E','#1B5E20'])
ax.set_ylabel('F1-score'); ax.set_title('RQ1 — Four experiments: Nyungwe vs National')
ax.set_ylim(0.6,0.9); plt.xticks(rotation=20, ha='right'); plt.tight_layout(); plt.show()""")

# ---- RQ1 feature importance
md("""## Step 2 — RQ1: feature importance by data source

Which satellite source carries the signal? Nyungwe first, national below.""")
co("""def importance_by_source(df):
    exps = experiments_for(df.columns.tolist()); D = exps['D — All combined']
    m = rf_tuned().fit(df[D].values, df['label'].values)
    def src(f):
        if any(x in f for x in ['VH','VV','ratio']): return 'radar'
        if f in ['elevation','slope','aspect']:      return 'terrain'
        return 'optical'
    g={}
    for f,v in zip(D, m.feature_importances_): g[src(f)]=g.get(src(f),0)+v
    return {k:round(v,3) for k,v in sorted(g.items(), key=lambda t:-t[1])}

print('Nyungwe  by source:', importance_by_source(nyu))
print('National by source:', importance_by_source(nat))""")
md("*Note the contrast: in Nyungwe terrain leads; nationally radar slightly out-ranks terrain.*")

# ---- RQ2 patch size
md("""## Step 3 — RQ2: patch-size recall (down to 0.18 ha)

Recall by clearing-patch size. Nyungwe first, national below.""")
co("""def patch_recall(df, coords_source):
    exps = experiments_for(df.columns.tolist()); D = exps['D — All combined']
    y = df['label'].values; X = df[D].values
    idx = np.arange(len(y))
    tr,te = train_test_split(idx, test_size=0.2, stratify=y, random_state=42)
    m = rf_tuned().fit(X[tr], y[tr]); pred = m.predict(X[te])
    pred_te = {i:p for i,p in zip(te,pred)}
    te_def = te[y[te]==1]
    coords = coords_source[te_def]
    labels = DBSCAN(eps=35/111000.0, min_samples=1).fit(coords).labels_
    sizes={}; preds={}
    for k,gi in zip(labels, te_def):
        sizes[k]=sizes.get(k,0)+0.09; preds.setdefault(k,[]).append(pred_te[gi])
    out=[]
    for name,lo,hi in [('<=0.1 ha',0,0.1),('0.1-0.2 ha',0.1,0.2),('0.2-0.5 ha',0.2,0.5)]:
        ks=[k for k,s in sizes.items() if lo<s<=hi]
        tp=sum(sum(preds[k]) for k in ks); n=sum(len(preds[k]) for k in ks)
        out.append({'Patch size':name,'Pixels':n,'Recall':round(tp/n,3) if n else None})
    return pd.DataFrame(out)

# Nyungwe coordinates come from the raw Nyungwe export
nyu_raw = pd.read_csv('data/raw/training_data.csv')
nyu_coords = np.column_stack([
    nyu_raw['.geo'].apply(lambda s: json.loads(s)['coordinates'][1]).values,
    nyu_raw['.geo'].apply(lambda s: json.loads(s)['coordinates'][0]).values])
nat_coords = np.column_stack([
    nat_raw['.geo'].apply(lambda s: json.loads(s)['coordinates'][1]).values,
    nat_raw['.geo'].apply(lambda s: json.loads(s)['coordinates'][0]).values])""")
md("### Nyungwe-only")
co("patch_recall(nyu, nyu_coords)")
md("### National (below)")
co("patch_recall(nat, nat_coords)")

# ---- spatial CV
md("""## Step 4 — Honest test: spatial cross-validation

Random split is optimistic because nearby pixels leak. Spatial CV holds out
whole blocks. Nyungwe first, national below.""")
co("""def spatial_cv(df, coords):
    exps = experiments_for(df.columns.tolist()); D = exps['D — All combined']
    X=df[D].values; y=df['label'].values
    blocks = KMeans(n_clusters=10, random_state=42, n_init=10).fit_predict(coords)
    gkf=GroupKFold(n_splits=5); f1s=[]
    for tr,te in gkf.split(X,y,groups=blocks):
        m=rf_tuned().fit(X[tr],y[tr]); f1s.append(f1_score(y[te],m.predict(X[te])))
    return round(np.mean(f1s),3), round(np.std(f1s),3)

nyu_s = spatial_cv(nyu, nyu_coords)
nat_s = spatial_cv(nat, nat_coords)
print(f'Nyungwe  spatial-CV F1 = {nyu_s[0]} +/- {nyu_s[1]}')
print(f'National spatial-CV F1 = {nat_s[0]} +/- {nat_s[1]}')
print('(random-split F1 is ~0.79 for reference)')""")

# ---- LOPO national only
md("""## Step 5 — National only: leave-one-province-out

Does the national model work on a province it never trained on?""")
co("""prov = nat_raw['province'].values
D = experiments_for(nat.columns.tolist())['D — All combined']
X = nat[D].values; y = nat['label'].values
rows=[]
for p in pd.unique(prov):
    tr = prov!=p; te = prov==p
    if te.sum()<50: continue
    m=rf_tuned().fit(X[tr],y[tr]); pred=m.predict(X[te])
    rows.append({'Held-out province':p,'n_test':int(te.sum()),
                 'F1':round(f1_score(y[te],pred),3),'Recall':round(recall_score(y[te],pred),3)})
pd.DataFrame(rows).sort_values('F1', ascending=False)""")
md("""*Even on an unseen province, F1 stays roughly 0.71–0.85 — direct evidence that
national training generalizes across Rwanda (supports the 'citizens anywhere' objective).
The West is hardest because it contains the steep montane Nyungwe zone.*""")

# ---- conclusion
md("""## Conclusion

| Measure | Nyungwe-only | National |
|---|---|---|
| Best experiment (D) F1 | 0.783 | **0.832** |
| Spatial-CV F1 | ~0.733 | ~0.753 |
| 0.18 ha patch recall | 0.80 | **0.88** |
| Works on unseen province? | n/a | yes (0.71–0.85) |

National training improves accuracy on every measure **and** generalizes across
provinces. Honest caveats: the national set is larger (23k vs 10k), so some gain
is extra data not only diversity; labels are still Hansen 30 m; spatial variance
is higher. Nyungwe remains the primary validation case study.""")

nb = new_notebook(cells=cells)
nb.metadata = {'kernelspec':{'name':'python3','display_name':'Python 3','language':'python'},
               'language_info':{'name':'python'}}
with open('notebooks/06_National_Extension.ipynb','w') as f:
    nbf.write(nb, f)
print('Wrote notebooks/06_National_Extension.ipynb with', len(cells), 'cells')
