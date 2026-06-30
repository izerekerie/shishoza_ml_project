# ════════════════════════════════════════════════════════════════════
#  Umurinzi — production container
#  • Python 3.13 slim
#  • Tesseract OCR (for cadastral PDF / photo extraction)
#  • poppler-utils (for pdfplumber text extraction)
#  • libgl1 (for OpenCV contour detection)
#  • gunicorn WSGI server, 4 workers, 90 s timeout (OCR is slow)
# ════════════════════════════════════════════════════════════════════

# ── Stage 1: build dependencies into a slim layer ───────────────────
FROM python:3.13-slim AS builder
WORKDIR /app

# System packages required by geopandas, pdfplumber, opencv, tesseract.
# Modern wheels for geopandas/shapely/pyproj include their own GEOS/PROJ so
# we don't need libgdal-dev here — saves ~500 MB in the final image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        poppler-utils \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps into a virtualenv so we can copy ONLY that to stage 2
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# ── Stage 2: lean runtime image ─────────────────────────────────────
FROM python:3.13-slim
WORKDIR /app

# Runtime-only system deps (Tesseract binary + poppler + libgl)
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        poppler-utils \
        libgl1 \
        libglib2.0-0 \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy the virtualenv from the builder stage
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Copy the application — only what the runtime actually needs
COPY app_cadastral.py .
COPY templates/ templates/
COPY scripts/ scripts/
COPY data/ data/
COPY results/ results/

# The 325 MB national model is too big for GitHub's repo (100 MB limit), so it's
# hosted on the Hugging Face Hub and downloaded here at build time. The HF repo
# (Kerie1/shishoza_model) is PUBLIC so no token is needed. The `test -s` guard
# fails the build loudly if the download is missing/empty instead of letting the
# app crash at boot. Update MODEL_URL if you republish the model elsewhere.
ARG MODEL_URL=https://huggingface.co/Kerie1/shishoza_model/resolve/main/rf_D_national.pkl
RUN mkdir -p models \
 && curl -fSL "$MODEL_URL" -o models/rf_D_national.pkl \
 && test -s models/rf_D_national.pkl \
 && echo "model downloaded: $(du -h models/rf_D_national.pkl | cut -f1)"

# Seed the SQLite DB (ALTERNATIVES + USERS) at container build time so the
# image is ready-to-run. seed_alternatives.sql creates the DB + ALTERNATIVES
# table; seed_users.py then adds the demo accounts. Without this the app boots
# with no alternatives AND no shared ANALYSIS_CACHE (multi-worker fix needs it).
RUN python -c "import sqlite3; con=sqlite3.connect('data/database/treesight.db'); con.executescript(open('data/database/seed_alternatives.sql').read()); con.close()" \
 && python scripts/seed_users.py

# Platform injects $PORT at runtime (Railway / Render) — fall back to 5050 for local
EXPOSE 5050
ENV PORT=5050

# Gunicorn config (exec form + `sh -c` so $PORT is ALWAYS shell-expanded —
# bare exec form leaves it literal, which Railway rejects: "'$PORT' is not a
# valid port number"). ${PORT:-5050} also defaults the port if none is injected.
#   --preload            load the 325 MB model ONCE in the master, share via COW
#                        across workers (avoids N× model RAM → cheaper tier OK)
#   --workers ${WEB_CONCURRENCY:-2}  override via env; 2 is enough for a demo
#   --timeout 90         the OCR path can take 30-60s on a Bugesera-scale PDF
CMD ["sh", "-c", "gunicorn app_cadastral:app --preload --workers ${WEB_CONCURRENCY:-2} --timeout 90 --bind 0.0.0.0:${PORT:-5050} --access-logfile - --error-logfile -"]
