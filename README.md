---
title: Shishoza
emoji: 🌳
colorFrom: green
colorTo: blue
sdk: docker
app_port: 5050
pinned: false
license: mit
---

# Shishoza — Rwanda Forest Risk Intelligence

> *Open-data satellite monitoring and localised risk assessment to help
> Rwandan citizens protect forest **before** cutting.*

> **Live on Hugging Face Spaces (Docker).** This YAML header is the Space
> config: `sdk: docker` builds the repo `Dockerfile`; `app_port: 5050` matches
> the port gunicorn binds to. The model is pulled from the Hugging Face Hub at
> build time, so the Space needs no extra setup.

---

## 1 · Description

Shishoza (Kinyarwanda for *guardian / protector*) is a BSc Software
Engineering capstone (African Leadership University) that addresses the
core gap in Rwanda's smallholder deforestation: most clearings are below
the 1-hectare detection threshold of published global forest monitoring,
so they're invisible until after the trees are gone.

The system combines:

- A **Random Forest classifier** trained on ~23,300 labelled pixels sampled
  province-stratified across all five of Rwanda's provinces, using Sentinel-2
  (optical) + Sentinel-1 (radar) + SRTM (terrain) features with Hansen Global
  Forest Change labels. The Nyungwe National Park buffer zone is retained as the
  primary validation case study.
- A **Flask web application** with three personas — Citizen, Forest
  Manager, Admin — each scoped to its real workflow.
- An **OpenAPI-documented REST backend** exposing 16 endpoints, browsable
  through interactive Swagger UI at `/apidocs`.

**Headline result**: the best model (all 17 features) scores **F1 = 0.83 under
5-fold cross-validation** and **F1 ≈ 0.75 under spatial cross-validation** — the
more conservative, geographically honest figure to quote. Both beat the published
global baseline (Ygorra et al. 2024, F1 = 0.71). Recall stays usable (~0.77 rising
to ~0.87) down to the 0.09–0.18 ha smallholder patch size where global models
typically degrade.

The system answers four research questions:

| RQ | Question | Status |
|---|---|---|
| RQ1 | Optimal combination of S2 / S1 / SRTM features? | Answered — `results/experiments/rq1_writeup.md` |
| RQ2 | Accuracy degradation at smallholder patch sizes? | Answered — `results/patch_size_analysis/` |
| RQ3 | Does 500 m neighbourhood improve over parcel-only analysis? | Answered — `RQ_FINDINGS_DRAFT.md` (implemented in app) |
| RQ4 | Out-of-sample validation across districts? | Pending — needs RNLA real-coordinate sample |

### Training data vs live data — why they use different years

The system uses satellite data for **two different jobs**, and they follow
different rules. This distinction matters for the defense:

| | **Training** (teach + measure the model) | **Live scoring** (use the model now) |
|---|---|---|
| Needs Hansen **labels**? | Yes — every pixel needs a known answer | No |
| Latest year the data exists | **2024** (Hansen ground truth lags ~1 yr) | **up to today** (Sentinel is an ongoing mission) |
| Years used | 2020 → 2024 | 2020 baseline + **2025–2026** recent window |
| Produces an F1 score? | **Yes — F1 ≈ 0.83** (this is the only place labels exist) | **No** — you cannot score accuracy without labels |
| Lives in | the notebooks | the live map / parcel lookup |

**Both windows produce the identical 17 features** — same NDVI, radar, terrain,
NDVI_change. The *only* differences: (a) which calendar window fills the
"recent" half of the vector, and (b) the 2020–24 data additionally carries a
Hansen `label` column. The model is year-agnostic: it takes 17 numbers and
returns a probability, so it consumes 2025–26 imagery natively.

**Why training stops at 2024:** training needs an answer key for every pixel,
and Hansen — the answer key — only publishes forest loss **through 2024**. There
is no 2025/2026 ground truth yet, so the model is *trained and validated* on
2020–24, then *applied* to current 2025–26 imagery for live predictions. This is
standard practice: learn from the labeled past, predict on the unlabeled present,
re-validate when new labels are published.

**Honest caveat:** F1 = 0.83 is measured on 2023–24 labels. Applying the model to
2025–26 is slightly beyond the validated window, so live accuracy is *assumed*,
not yet *measured* — it will be re-checked once Hansen releases 2025/2026 loss.

> Refresh the live sector map by running `notebooks/02b_GEE_Export_Sectors_Current.js`
> in Earth Engine, then `scripts/precompute_sector_current.py`.

---

## 2 · Repository

| Resource | URL |
|---|---|
| **GitHub repo** | https://github.com/izerekerie/shishoza_ml_project |
| **Demo video & deliverables (Google Drive)** | https://drive.google.com/drive/folders/1e_M-3ZgYuXzDoA0rYtnfsLZew7jWrzK3?usp=sharing |
| **Live demo (Railway)** | `https://shishoza.up.railway.app` — *deployed, beta: slow first boot / cold start (see §5)* |
| Swagger UI | `https://shishoza.up.railway.app/apidocs` — or `http://localhost:5050/apidocs` when running locally |
| Dissertation prose | `results/experiments/rq1_writeup.md` |

To clone:

```bash
git clone https://github.com/izerekerie/shishoza_ml_project.git
cd shishoza_ml_project
```

---

## 3 · Environment & project setup

### Prerequisites

| Tool | Version | Why |
|---|---|---|
| Python | 3.11 or 3.13 | Project tested on 3.13 |
| Tesseract OCR | 5.x | Citizen cadastral upload reads printed labels |
| Poppler | 23.x+ | PDF text extraction (pdfplumber) |
| Git | any | Cloning |
| Docker (optional) | 24+ | Reproducible deploy; see DEPLOYMENT.md |

#### macOS install

```bash
brew install python@3.13 tesseract poppler git
```

#### Ubuntu / Debian install

```bash
sudo apt update
sudo apt install -y python3.13 python3.13-venv \
                    tesseract-ocr poppler-utils \
                    libgl1 libglib2.0-0 git
```

### Project setup (4 commands)

```bash
# 1. Create + activate a virtualenv
python3.13 -m venv .venv
source .venv/bin/activate

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Seed the SQLite database with bcrypt-hashed demo accounts
python scripts/seed_users.py

# 4. Run the Flask app
python app_cadastral.py
```

Then open **http://localhost:5050**.

### Demo accounts

| Role | Email | Password | Sees |
|---|---|---|---|
| Admin | `admin@treesight.rw` | `admin` | Everything (all 416 sectors + user management) |
| Forest Manager | `manager.nyamasheke@treesight.rw` | `nyamasheke` | Nyamasheke district sectors only |
| Forest Manager | `manager.rusizi@treesight.rw` | `rusizi` | Rusizi district sectors only |
| Forest Manager | `manager.nyaruguru@treesight.rw` | `nyaruguru` | Nyaruguru district sectors only |

### Folder structure (each folder has ONE purpose)

```
shishoza/
├── data/
│   ├── raw/          GEE exports (training_data.csv) + sample cadastral PDFs
│   ├── processed/    Cleaned training data
│   ├── geo/          Sector polygons + Hansen rasters
│   └── database/     SQLite + seed SQL
├── notebooks/        GEE script + 6 Jupyter notebooks
├── scripts/          7 reproducible pipeline scripts
├── models/           4 trained Random Forest models (rf_A..D.pkl)
├── results/
│   ├── eda/                       5 exploratory data analysis figures
│   ├── experiments/                4-experiment comparison (RQ1)
│   ├── hyperparameter_tuning/      96-combo grid search outputs
│   ├── metrics/                    F1, confusion matrix, audit JSON
│   ├── patch_size_analysis/        RQ2 figure + CSV
│   └── application/                Precomputed sector_risk.json
├── app_cadastral.py               Flask web app entry point
├── Dockerfile                      Production container (Railway / Render)
├── railway.json                    Railway deploy config (live platform)
├── render.yaml                     Render blueprint (alternative platform)
├── requirements.txt
├── README.md                       This file
└── DEPLOYMENT.md                   Step-by-step deploy guide
```

### Reproducibility chain

Running these scripts in order rebuilds the whole pipeline from the raw
GEE export onwards:

```bash
# Data prep (notebooks)
# notebooks/01_GEE_Export.js       runs in the GEE code editor
jupyter nbconvert --to notebook --execute notebooks/02_Clean_Data.ipynb
jupyter nbconvert --to notebook --execute notebooks/03_Train_Model.ipynb

# Reproducible analysis scripts
python scripts/eda_visualisations.py            # → results/eda/*.png
python scripts/hyperparameter_tune.py            # → results/hyperparameter_tuning/
python scripts/evaluate_split_and_patchsize.py   # → results/metrics/ + patch_size_analysis/
python scripts/rq1_writeup.py                    # → results/experiments/rq1_*
python scripts/precompute_sector_risk.py         # → results/application/sector_risk.json
```

---

## 4 · Designs

### 4.1 Figma mockups

The visual design system was prototyped in Figma before any HTML was
written. The mockups cover all five user-facing views — landing, login,
citizen, forest manager, and admin.

**Figma file:** https://www.figma.com/design/mYF9We3btINQNbOsiuRl5I/Shishoza?node-id=0-1

Design system in use (replicated 1:1 in the Flask templates):

```
Primary brand        #14532d   (forest green)
Hover                #166534
Background           #f7f8f5
Card background      #ffffff
Risk HIGH            #dc2626
Risk MEDIUM          #ea580c
Risk LOW             #16a34a
Muted text           #6b7280
```

### 4.2 Architecture diagrams

Architecture diagrams documented in Chapter 3 of the dissertation. Shishoza is
a software-only system, so the "circuit diagram" requirement is met by the
system data-flow and entity-relationship diagrams below.

<img width="842" height="1251" alt="System architecture" src="https://github.com/user-attachments/assets/eef68975-f8ec-45e5-8deb-1a6f39c9d093" />

<img width="1465" height="1629" alt="Data flow and ERD" src="https://github.com/user-attachments/assets/91b4fbc2-1813-47af-9c55-cb0158dbf707" />

### 4.3 App interface

A full walkthrough of all five views (landing, login, citizen, forest
manager, admin) is in the **[demo video](https://drive.google.com/drive/folders/1e_M-3ZgYuXzDoA0rYtnfsLZew7jWrzK3?usp=sharing)**.

Screenshots:

<img width="1512" height="824" alt="Screenshot 2026-06-12 at 20 49 47" src="https://github.com/user-attachments/assets/09987a0a-ac6f-42ad-9f56-c89a53809d7e" />
<img width="1512" height="824" alt="Screenshot 2026-06-12 at 20 53 27" src="https://github.com/user-attachments/assets/1f696abb-0e76-472c-ae82-f055e2c62bef" />
<img width="1512" height="824" alt="Screenshot 2026-06-12 at 20 53 33" src="https://github.com/user-attachments/assets/0bba2a6d-a566-4934-8df0-8288f27bbccb" />
<img width="1512" height="824" alt="Screenshot 2026-06-12 at 20 53 49" src="https://github.com/user-attachments/assets/af883271-8fc1-4486-b995-a38ef8f8beb3" />
<img width="1512" height="824" alt="Screenshot 2026-06-12 at 20 53 56" src="https://github.com/user-attachments/assets/9f0375ba-74f9-4158-b37f-90019998b0a7" />
<img width="1512" height="824" alt="Screenshot 2026-06-12 at 20 54 08" src="https://github.com/user-attachments/assets/cae91233-e30d-4509-8c79-e64e7d3f8b11" />
<img width="1512" height="824" alt="Screenshot 2026-06-12 at 20 54 28" src="https://github.com/user-attachments/assets/c3686af8-8fd0-493f-8482-07453af97a87" />


---

## 5 · Deployment

**Status: deployed (beta).** The app is live on **Railway** at `https://shishoza.up.railway.app`,
built from the included `Dockerfile` + `railway.json`. It is honestly a *beta*
deployment — see [Known limitations](#known-limitations) below.

The app is a single Flask service that serves both the web pages and the REST API
from one process, so it deploys as one web service — no separate frontend host is
required. The container ships with the trained model, sector polygons, and the
Hansen-derived `sector_risk.json` pre-loaded, so there are **zero runtime external
dependencies** (Google Earth Engine and Hansen are only used offline at training time).

### Tools & files

| File | Role in deployment |
|---|---|
| `Dockerfile` | Builds the production image (Python 3.13-slim + tesseract + opencv + gunicorn) |
| `railway.json` | Railway config: Dockerfile builder, `/api/me` healthcheck, 300 s healthcheck timeout, restart-on-failure |
| `.dockerignore` | Keeps the build context small (skips notebooks, drafts, `.venv`) |
| `requirements.txt` | Pins Python deps, including `gunicorn` (production WSGI server) |
| Hugging Face | The large national model is pulled at build time (kept out of Git) |

### Environments

| Environment | How it runs | URL |
|---|---|---|
| **Local dev** | `python app_cadastral.py` (Flask dev server) | `http://localhost:5050` |
| **Local prod-parity** | `docker run` (gunicorn, same image as prod) | `http://localhost:5050` |
| **Production (target)** | Railway service, auto-deploys on `git push` | `https://shishoza.up.railway.app` |

### Deploy steps (Railway)

1. Push to GitHub (`main`).
2. Railway → **New Project → Deploy from GitHub repo** → select this repo.
3. Railway reads `railway.json` and builds from the `Dockerfile` (~6–8 min first build).
4. Set the `SHISHOZA_SECRET` environment variable (Railway can generate one) before going public.
5. Railway waits for the `/api/me` healthcheck (timeout raised to 300 s because the
   model load makes the first boot slow), then routes traffic to the new build.

### Verify it before pushing — local Docker (prod parity)

```bash
docker build -t shishoza .
docker run -p 5050:5050 -e PORT=5050 -e SHISHOZA_SECRET=dev shishoza
# → open http://localhost:5050  (same image Railway runs)
```

### Verification done in the target environment

After each deploy, the following were checked on the live Railway URL:

- `GET /api/me` returns 200 (the healthcheck Railway gates on).
- Landing, `/login`, `/citizen`, `/manager`, `/admin` all render.
- Login with the demo accounts (§3) succeeds and scopes each manager to their district.
- `/apidocs` Swagger UI loads and a sample `/api/analyse` call returns a risk classification.

### <a name="known-limitations"></a>Known limitations (why it's "beta")

- **Slow first boot / cold start.** Loading the ~47 MB model + 416 sector polygons
  pushes boot to ~600 MB and tens of seconds, which is why the healthcheck timeout
  is 300 s. The first request after an idle period can be slow.
- **Free-credit ceiling.** Railway's free credit is consumed quickly by an always-on
  service, so the demo may sleep or stop when credit runs low.
- For an always-on production pilot, `DEPLOYMENT.md` compares paid options
  (Render Standard, Fly.io, a small VM) with a full cost breakdown.

### Run locally without Docker (plain Python — see §3 for prerequisites)

```bash
python3.13 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/seed_users.py       # one-time: seed demo accounts
python app_cadastral.py
# → http://localhost:5050
```

---

## 6 · Results & analysis against proposal objectives

This section maps each **specific objective** from the capstone proposal to what
was actually delivered, with honest notes where results deviate. The proposal set
three specific objectives, evaluated against the published baseline of **F1 > 0.71**
(Ygorra et al. 2024, the best international result for small-scale deforestation).

| # | Proposal objective | Outcome | Evidence |
|---|---|---|---|
| **O1** | Review the literature (2019–26) and collect a balanced, labelled GEE dataset (Sentinel-2 + Sentinel-1 + SRTM + Hansen), province-stratified across all 5 provinces for 2020–2024, with the Nyungwe buffer as the validation case study. | **Met.** A national, province-stratified sample of ~23,300 labelled pixels with the 17-feature schema was exported from Earth Engine; the Nyungwe buffer is retained as the validation zone. | `notebooks/01_GEE_Export_National.js`, `data/processed/`, `results/eda/` |
| **O2** | Train a Random Forest comparing **4 feature combinations** and integrate the best model into one responsive, Dockerised web app showing deforestation to managers and letting citizens locate their parcel and see tree-loss-since-2020, 500 m neighbourhood recovery, and a HIGH/MEDIUM/LOW risk class *before* a permit. | **Met, with one platform deviation.** Four feature sets (A–D) were compared; the best is **D (all 17 features)**. The Flask app delivers Citizen / Manager / Admin personas, per-parcel risk, the 500 m neighbourhood analysis, and a cut simulation. Deployed Dockerised — on **Railway, not Render** (cost/credit; see §5). | `notebooks/03_Train_Model.ipynb`, `models/rf_D*.pkl`, `app_cadastral.py` |
| **O3** | Evaluate whether the system closes the gap: model **F1 > 0.71**, and the app delivers satellite tree-cover + risk to citizens at their location. | **Met on accuracy; partially met on external validation.** Best model **F1 = 0.83 (5-fold CV) / 0.75 (spatial CV)** — both clear 0.71. The app delivers the information end-to-end. Cross-district out-of-sample validation (RQ4) is still pending. | `results/metrics/`, `RQ_FINDINGS_DRAFT.md` |

### How the headline result was achieved

The accuracy gain comes from **fusing all three data sources** (optical + radar +
terrain) into a 200-tree Random Forest on province-stratified national data. The
research questions decompose *why* it works:

- **RQ1 (feature fusion).** Adding radar to optical lifts F1 by +0.039; the full
  17-feature model is best (F1 = 0.83 CV). Decision weight splits optical 50.7 % /
  radar 25.9 % / terrain 23.4 % — radar is a justified, non-redundant component.
- **RQ2 (smallholder patch size).** Recall stays usable down to parcel scale —
  ~0.77 at 0.09–0.18 ha, rising to 0.87 above 1.8 ha — i.e. the system recovers
  ~3 in 4 of the sub-hectare clearings that global products miss.
- **RQ3 (500 m neighbourhood).** Adds cumulative-pressure and recovery-trajectory
  evidence, plus a forward cut-simulation with a ~6–8 year recovery estimate, that a
  single-parcel permit review cannot see.

### Honest gaps — where results fall short of the proposal

- **Two F1 numbers, reported honestly.** Random / 5-fold CV gives ≈ 0.79–0.83;
  **spatial CV** (train and test on geographically separate blocks) gives ≈ **0.75**.
  Spatial CV is the defensible generalization figure and is the one to quote — it
  still beats the 0.71 baseline, but the gap is smaller than a random split suggests.
- **Live-scoring accuracy is assumed, not measured.** The model is validated on
  2020–2024 Hansen labels and *applied* to current 2025–26 imagery; there is no
  2025–26 ground truth yet, so live accuracy will only be confirmed when Hansen
  publishes those labels (see §1).
- **RQ4 (multi-district out-of-sample validation) is pending** — it needs a
  real-coordinate sample (e.g. from RNLA) outside the training footprint.
- **Deployment platform changed** from the proposal's Render to **Railway** (cost /
  free-credit reasons); the deviation and alternatives are documented in §5 and `DEPLOYMENT.md`.
- **Citizen parcel location** is implemented via land-certificate upload and manual
  coordinate entry rather than the pure browser-GPS flow described in the proposal.

### Linkage to project scope

The work stays inside the proposal's scope: **train nationally** (province-stratified
across all five provinces so the model learns Rwanda's full landscape) while
**validating on the Nyungwe buffer** — Rwanda's most documented smallholder
deforestation zone. The whole system is aimed squarely at the documented gap: making
**sub-hectare, pre-permit** deforestation risk visible to citizens and managers, which
no existing Rwandan tool offers before a clearing decision is made.

---

## License

This project is part of an undergraduate research deliverable at
African Leadership University. All third-party tools used are
open-source (MIT, BSD, or Apache 2.0). Satellite imagery is provided
under the European Space Agency, USGS, and University of Maryland open
data licences for academic use.
