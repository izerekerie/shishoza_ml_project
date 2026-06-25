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
    && rm -rf /var/lib/apt/lists/*

# Copy the virtualenv from the builder stage
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Copy the application — only what the runtime actually needs
COPY app_cadastral.py .
COPY scripts/ scripts/
COPY data/ data/
COPY results/ results/
COPY models/ models/

# Seed the SQLite USERS table at container build time so the image is
# ready-to-run. Anyone deploying gets the demo accounts pre-loaded.
RUN python scripts/seed_users.py

# Platform injects $PORT at runtime (Railway / Render) — fall back to 5050 for local
EXPOSE 5050
ENV PORT=5050

# Gunicorn config:
#   --workers 4          handles ~10-20 concurrent users (sync worker mode)
#   --timeout 90         the OCR path can take 30-60s on a Bugesera-scale PDF
#   --bind 0.0.0.0:$PORT bind to the platform-injected port
CMD gunicorn app_cadastral:app \
    --workers 4 \
    --timeout 90 \
    --bind 0.0.0.0:$PORT \
    --access-logfile - \
    --error-logfile -
