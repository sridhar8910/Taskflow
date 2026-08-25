# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy ONLY pyproject.toml first so this layer is cached unless deps change
COPY pyproject.toml .
# Create a minimal stub package so pip can install dependencies
# (the actual source is bind-mounted at runtime, so only deps need to be here)
RUN mkdir -p app && touch app/__init__.py
# hadolint ignore=DL3013
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir --prefix=/install ".[dev]"

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Runtime system deps (libpq for asyncpg/psycopg2)
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY . .

# Non-root user for security
# Also pre-create /var/lib/celerybeat so the named volume mount is writable
# by appuser (Docker volumes are created root-owned by default).
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app && \
    mkdir -p /var/lib/celerybeat && \
    chown -R appuser:appuser /var/lib/celerybeat
USER appuser

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
