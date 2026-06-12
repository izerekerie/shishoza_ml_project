# Umurinzi — Rwanda Forest Risk Intelligence

> *Open-data satellite monitoring and localised risk assessment to help
> Rwandan citizens protect forest **before** cutting.*

---

## 1 · Description

Umurinzi (Kinyarwanda for *guardian / protector*) is a BSc Software
Engineering capstone (African Leadership University) that addresses the
core gap in Rwanda's smallholder deforestation: most clearings are below
the 1-hectare detection threshold of published global forest monitoring,
so they're invisible until after the trees are gone.

The system combines:

- A **Random Forest classifier** trained on 10,000 labelled pixels from
  the Nyungwe buffer zone using Sentinel-2 (optical) + Sentinel-1 (radar)
  + SRTM (terrain) features, with Hansen Global Forest Change labels.
- A **Flask web application** with three personas — Citizen, Forest
  Manager, Admin — each scoped to its real workflow.
- An **OpenAPI-documented REST backend** exposing 16 endpoints, browsable
  through interactive Swagger UI at `/apidocs`.

**Headline result**: F1 = 0.791 on a held-out 2,000-pixel test set,
beating the published global baseline (Ygorra et al. 2024, F1 = 0.71) by
**+0.08**. Recall stays in the 80–83 % band even at the 0.1–0.2 ha
smallholder patch size where global models typically degrade.

The system answers four research questions:

| RQ | Question | Status |
|---|---|---|
| RQ1 | Optimal combination of S2 / S1 / SRTM features? | ✅ Answered — `results/experiments/rq1_writeup.md` |
| RQ2 | Accuracy degradation at smallholder patch sizes? | ✅ Answered — `results/patch_size_analysis/` |
| RQ3 | Does 500 m neighbourhood improve over parcel-only analysis? | 🟡 Implemented in app; writeup pending |
| RQ4 | Out-of-sample validation across districts? | 🟡 Pending — needs RNLA real-coordinate sample |

---

## 2 · Repository

| Resource | URL |
|---|---|
| **GitHub repo** | https://github.com/<your-username>/umurinzi *(replace once pushed)* |
| Live demo URL | https://umurinzi-web.onrender.com *(once deployed; see DEPLOYMENT.md)* |
| Swagger UI | `<demo-url>/apidocs` |
| Dissertation prose | `results/experiments/rq1_writeup.md`, Chapter 3/4 docx (not in repo) |

To clone:

```bash
git clone https://github.com/<your-username>/umurinzi.git
cd umurinzi
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
umurinzi/
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
├── Dockerfile                      Production container (Render-ready)
├── render.yaml                     Render Infrastructure-as-Code
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
written. The mockups cover all five user-facing views.

| Page | Figma URL |
|---|---|
| Landing (choose role) | https://www.figma.com/file/<your-id>/umurinzi-landing |
| Login | https://www.figma.com/file/<your-id>/umurinzi-login |
| Citizen view | https://www.figma.com/file/<your-id>/umurinzi-citizen |
| Forest Manager dashboard | https://www.figma.com/file/<your-id>/umurinzi-manager |
| Admin user management | https://www.figma.com/file/<your-id>/umurinzi-admin |

*(Replace `<your-id>` placeholders with your actual Figma file IDs.)*

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

Five architecture diagrams documented in Chapter 3 of the dissertation:

| Fig | Description | File reference |
|---|---|---|
| 3.1 | Two-pipeline system architecture (offline training + online inference) | Chapter 3 §3.X |
| 3.2 | Use-case diagram (Citizen, Forest Manager, Admin) | Chapter 3 §3.X |
| 3.3 | Data-pipeline sequence (GEE → labels → features → model) | Chapter 3 §3.X |
| 3.4 | API request sequence (citizen upload → OCR → analysis) | Chapter 3 §3.X |
| 3.5 | Entity-Relationship Diagram (USERS / SECTORS / PARCEL_ANALYSES / ALTERNATIVES) | Chapter 3 §3.X |

These are not circuit diagrams (Umurinzi is a software-only project — no
hardware sensors), so the "circuit diagram" rubric line is interpreted as
the **data-flow + ERD** combination above.

### 4.3 App interface screenshots

Reference screenshots produced during development:

| Screenshot | File |
|---|---|
| Swagger UI (`/apidocs`) | `results/eda/swagger_ui.png` |
| Landing page | *(capture from running app; add to `results/screenshots/`)* |
| Citizen — upload + analyse | *(capture from running app)* |
| Citizen — simulation slider | *(capture from running app)* |
| Manager — choropleth + click-to-analyse | *(capture from running app)* |
| Admin — user list + add-user modal | *(capture from running app)* |
| Login page | *(capture from running app)* |

To capture screenshots manually:

```bash
python app_cadastral.py   # start the app
# Visit each URL in a browser and use ⌘+Shift+4 (macOS) or your OS screenshot tool
# Save into results/screenshots/01_landing.png, 02_citizen_upload.png, etc.
```

---

## 5 · Deployment plan

The full deployment plan with cost table, alternatives, and rollback
procedures lives in **`DEPLOYMENT.md`**. The headline:

### Recommended platform: Render + Docker

```
Why            Auto-deploys on `git push`, free HTTPS + custom domain,
                2 GB RAM tier handles the 600 MB boot footprint
Cost (viva)    USD 0   (Render free tier; 30 s cold start documented)
Cost (pilot)   USD 25/month   (Render Standard, always-on)
Region          Frankfurt (closest to Rwanda)
WSGI server     gunicorn × 4 workers, 90 s timeout (OCR is slow)
```

### One-command local Docker test

```bash
docker build -t umurinzi:latest .
docker run -p 5050:5050 -e PORT=5050 umurinzi:latest
# → http://localhost:5050
```

### One-click cloud deploy

```bash
# After pushing to GitHub:
# 1. Go to https://render.com → New → Blueprint
# 2. Connect this repo
# 3. Render reads render.yaml and provisions the service
# 4. First build: ~6-8 minutes; subsequent: ~2-3 minutes
# 5. Live URL: https://umurinzi-web.onrender.com
```

### Cost summary (matches the proposal's updated budget table)

| Component | Plan | Cost |
|---|---|---|
| All ML tooling (GEE, scikit-learn, Flask, Tesseract, etc.) | Open-source | USD 0 |
| Source code hosting | GitHub free tier | USD 0 |
| Container registry | Docker Hub free / GHCR free | USD 0 |
| **Viva-day demo hosting** | **Render Free (cold starts)** | **USD 0** |
| Production demo hosting | Render Standard (2 GB RAM, always-on) | USD 25 / month |
| Optional custom domain `umurinzi.rw` | RICTA registrar | ~USD 1 / month amortised |
| **TOTAL — viva** | | **USD 0** |
| **TOTAL — production pilot** | | **~USD 26 / month** |

The full breakdown — including cheaper alternatives (Fly.io, Railway,
DigitalOcean Droplet, Hetzner CPX11) — is in **`DEPLOYMENT.md`**.

### Production checklist before the viva

```
[ ] Push to GitHub with .gitignore properly excluding drafts + utility scripts
[ ] Confirm Docker image builds locally
[ ] Connect repo to Render via render.yaml blueprint
[ ] Wait for first build (~6-8 min)
[ ] Set SECRET_KEY env var (NOT the hardcoded BSc demo key)
[ ] Confirm /api/me returns 200 publicly
[ ] Test full citizen flow end-to-end
[ ] Test manager login + click-to-analyse end-to-end
[ ] Test admin user-management end-to-end
[ ] Set up UptimeRobot monitor (free) on /api/me
[ ] Capture screenshots from the live URL for the dissertation
[ ] Document the live URL in the dissertation results chapter
```

---

## License

This project is part of an undergraduate research deliverable at
African Leadership University. All third-party tools used are
open-source (MIT, BSD, or Apache 2.0). Satellite imagery is provided
under the European Space Agency, USGS, and University of Maryland open
data licences for academic use.
