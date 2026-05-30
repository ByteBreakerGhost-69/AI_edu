# ============================================================
# Stage 1: Builder — install Python dependencies
# ============================================================
FROM python:3.11-slim AS builder

WORKDIR /app

# Build-time system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry into its own isolated venv
ENV POETRY_VERSION=1.8.3
ENV POETRY_HOME=/opt/poetry
ENV POETRY_VENV=/opt/poetry-venv
ENV POETRY_CACHE_DIR=/opt/.cache

RUN python3 -m venv $POETRY_VENV \
    && $POETRY_VENV/bin/pip install --upgrade pip setuptools \
    && $POETRY_VENV/bin/pip install "poetry==${POETRY_VERSION}"

ENV PATH="${POETRY_VENV}/bin:${PATH}"

# Copy dependency manifests only — leverages Docker layer cache
COPY pyproject.toml poetry.lock* ./

# Install production dependencies directly into system Python
# (virtualenvs disabled — we're already in a container)
RUN poetry config virtualenvs.create false \
    && poetry install \
        --only=main \
        --no-root \
        --no-interaction \
        --no-ansi

# ============================================================
# Stage 2: Runtime — lean production image
# ============================================================
FROM python:3.11-slim AS runtime

WORKDIR /app

# --------------------------------------------------------------------------- #
# System runtime dependencies                                                  #
# --------------------------------------------------------------------------- #
RUN apt-get update && apt-get install -y --no-install-recommends \
    # ---- FFmpeg (core rendering pipeline) ----
    ffmpeg \
    \
    # ---- Cairo / Pango / GdkPixbuf for cairosvg (diagram_renderer) ----
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi8 \
    shared-mime-info \
    \
    # ---- Chromium for Lottie renderer (pyppeteer) ----
    chromium \
    \
    # ---- Fonts: DejaVu (code_renderer monospace) + Liberation ----
    fonts-dejavu-core \
    fonts-liberation \
    \
    # ---- LaTeX for Manim MathTex rendering ----
    texlive-latex-base \
    texlive-fonts-recommended \
    texlive-latex-extra \
    dvipng \
    cm-super \
    \
    # ---- Node.js for Mermaid CLI ----
    nodejs \
    npm \
    \
    # ---- curl for HEALTHCHECK ----
    curl \
    \
    && rm -rf /var/lib/apt/lists/*

# Install Mermaid CLI globally (pinned version for reproducibility)
RUN npm install -g @mermaid-js/mermaid-cli@10.9.1 \
    && mmdc --version

# --------------------------------------------------------------------------- #
# Copy Python packages from builder stage                                      #
# --------------------------------------------------------------------------- #
COPY --from=builder /usr/local/lib/python3.11/site-packages \
                    /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# --------------------------------------------------------------------------- #
# Application code                                                             #
# --------------------------------------------------------------------------- #
COPY . .

# --------------------------------------------------------------------------- #
# Filesystem setup                                                             #
# --------------------------------------------------------------------------- #

# Rendering temp directory
RUN mkdir -p /tmp/edu_video && chmod 777 /tmp/edu_video

# Non-root user for security (Cloud Run best practice)
RUN groupadd --gid 1001 appgroup \
    && useradd \
        --uid 1001 \
        --gid appgroup \
        --shell /bin/bash \
        --create-home \
        appuser \
    && chown -R appuser:appgroup /app \
    && chown -R appuser:appgroup /tmp/edu_video

# --------------------------------------------------------------------------- #
# Environment defaults                                                         #
# Override via Cloud Run environment variables or .env for local dev           #
# --------------------------------------------------------------------------- #
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    APP_ENV=prod \
    RENDER_TEMP_DIR=/tmp/edu_video \
    PUPPETEER_EXECUTABLE=/usr/bin/chromium \
    MERMAID_CLI_PATH=/usr/local/bin/mmdc \
    # Manim settings
    MANIM_QUALITY=high \
    # Disable Manim's interactive output in container
    MANIM_VERBOSITY=WARNING

USER appuser

# --------------------------------------------------------------------------- #
# Health check                                                                 #
# Cloud Run / Kubernetes liveness probe                                        #
# --------------------------------------------------------------------------- #
HEALTHCHECK \
    --interval=30s \
    --timeout=10s \
    --start-period=90s \
    --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

EXPOSE 8080

# --------------------------------------------------------------------------- #
# Production entrypoint                                                        #
# gunicorn manages uvicorn workers for graceful restarts + multi-process       #
# 2 workers: suitable for Cloud Run min-instance=1, scales per-request        #
# timeout=300: accommodates long video generation API responses                #
# --------------------------------------------------------------------------- #
CMD ["gunicorn", "main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "2", \
     "--bind", "0.0.0.0:8080", \
     "--timeout", "300", \
     "--keep-alive", "5", \
     "--max-requests", "1000", \
     "--max-requests-jitter", "100", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--log-level", "info"]
