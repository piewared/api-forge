# syntax=docker/dockerfile:1
# FastAPI Application Production Dockerfile
# Multi-stage build for optimal security and performance
# Using Debian slim instead of Alpine for better compatibility with pre-built wheels

# =============================================================================
# Stage 1: Build environment
# =============================================================================
FROM python:3.13-slim AS builder

# Install build dependencies (minimal for using pre-built wheels)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev git \
    && rm -rf /var/lib/apt/lists/*

# Create and set working directory
WORKDIR /build

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install uv for fast dependency management
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir uv

# Install dependencies to a virtual environment
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH"

# Install dependencies from the lockfile for reproducible builds.
# --frozen ensures the exact versions pinned in uv.lock are used, not
# freshly resolved ones, so Docker images match the local development env.
# UV_PROJECT_ENVIRONMENT points uv sync at the venv we just created so
# packages go into /opt/venv (not the default .venv in the build dir).
RUN --mount=type=cache,target=/root/.cache/uv \
    UV_PROJECT_ENVIRONMENT=/opt/venv uv sync --frozen --no-dev --no-install-project

# =============================================================================
# Stage 2: Production environment
# =============================================================================
FROM python:3.13-slim AS production

# Install runtime dependencies only
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates tzdata tini gosu libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# Create app user for security
RUN groupadd -g 1001 appgroup && \
    useradd -u 1001 -g appgroup -s /bin/bash -m appuser

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Set PATH to use virtual environment
ENV PATH="/opt/venv/bin:$PATH"

# Set working directory
WORKDIR /app

# Copy application code
COPY --chown=appuser:appgroup src/ src/
COPY --chown=appuser:appgroup src_main.py ./
COPY --chown=appuser:appgroup config.yaml ./

# Copy universal entrypoint script
COPY infra/docker/prod/scripts/universal-entrypoint.sh /usr/local/bin/universal-entrypoint.sh
RUN chmod +x /usr/local/bin/universal-entrypoint.sh

# Create necessary directories with proper permissions
RUN mkdir -p /app/logs /app/data && \
    chown -R appuser:appgroup /app

# Note: We start as root to handle secret permissions, then drop to appuser in entrypoint
# USER appuser will be handled by entrypoint.sh

# Environment variables for production
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENVIRONMENT=production

# Expose application port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Use tini as init process for proper signal handling
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/universal-entrypoint.sh"]

# Create secrets directories with secure permissions (0700 = owner only)
RUN install -d -m 0700 -o appuser -g appgroup /app/keys && \
    install -d -m 0700 -o appuser -g appgroup /app/certs

# Start application
CMD ["uvicorn", "src_main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
