# nogran.trader.agent — application image
#
# Builds a lean image containing the Python agent + Streamlit dashboard.
# The Kraken CLI binary is NOT bundled (out-of-scope for the demo image).
# For live paper trading, install kraken-cli on the host and use Docker
# bind mounts, or extend this Dockerfile.
#
# Build:
#     docker build -t nogran-trader-agent:latest .
#
# Run dashboard alone (demo mode):
#     docker run --rm -p 8501:8501 -e DEMO_MODE=1 nogran-trader-agent:latest dashboard
#
# Run agent (requires OPENAI_API_KEY):
#     docker run --rm -e OPENAI_API_KEY=sk-... nogran-trader-agent:latest agent

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System deps: only what's needed for python deps + healthcheck
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for better layer caching.
# We use the curated requirements files (not requirements.lock) to keep the
# image lean — lock file has 87 packages including dev tooling.
COPY requirements.txt ./
COPY dashboard/requirements.txt ./dashboard-requirements.txt
RUN pip install --upgrade pip \
    && pip install -r requirements.txt -r dashboard-requirements.txt

# Copy application code
COPY src/ ./src/
COPY data/ ./data/
COPY dashboard/ ./dashboard/
COPY scripts/ ./scripts/
COPY pyproject.toml ./

# Logs directory (mounted as volume in production)
RUN mkdir -p /app/logs/decisions

# Non-root user for runtime
RUN useradd -u 1000 -m trader \
    && chown -R trader:trader /app
USER trader

EXPOSE 8501

# Entrypoint dispatcher: pass "agent" or "dashboard" as the command.
COPY --chown=trader:trader docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh || true

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["dashboard"]
