# ── Build stage: install dependencies ──────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# Build-time system deps (gcc for compiling some packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install --no-cache-dir uv

# Copy only dependency files first (better layer caching)
COPY pyproject.toml uv.lock ./

# Install production dependencies only (no dev group)
RUN uv sync --frozen --no-dev --no-install-project

# ── Runtime stage ────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

# Runtime system deps only (libpq for asyncpg, curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder (no gcc/build tools in final image)
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY backend/ ./backend/

# Use venv python directly (faster than uv run, no uv overhead in prod)
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app/backend
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Run as non-root user
RUN useradd -r -u 1001 -s /sbin/nologin appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health/ || exit 1

CMD ["python", "-m", "backend.main"]
