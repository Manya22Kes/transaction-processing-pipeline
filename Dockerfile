# ─────────────────────────────────────────────────────────────────
#  Multi-stage Dockerfile
#  Stage 1 – builder: install Python deps into a venv
#  Stage 2 – runtime: copy the venv and app code only
#  This keeps the final image lean and avoids build-tool pollution.
# ─────────────────────────────────────────────────────────────────

# ── Stage 1: dependency builder ──────────────────────────────────
FROM python:3.12-slim AS builder

# Install OS packages needed to compile psycopg2 and other C extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy only the requirements file first so Docker caches this layer
# and re-uses it on code-only changes.
COPY requirements.txt .

# Create and populate a virtual environment inside the build stage
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt


# ── Stage 2: runtime ─────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Runtime OS deps (libpq is needed at runtime for psycopg2)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN groupadd --gid 1001 appgroup && \
    useradd  --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

# Copy the venv from the builder stage
COPY --from=builder /opt/venv /opt/venv

# Put venv on PATH
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Copy application source code
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini ./alembic.ini

# Create uploads directory with correct permissions
RUN mkdir -p /app/uploads && chown -R appuser:appgroup /app

USER appuser

# Default command — overridden in docker-compose for the worker
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
