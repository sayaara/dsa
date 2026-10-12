# syntax=docker/dockerfile:1.7

# ===================================
# US/Canada stock analysis system - Docker image
# ===================================
# Multi-stage build: web bundle, then the backend runtime

FROM node:20-slim AS web-builder

WORKDIR /app/apps/dsa-web
ARG DSA_WEB_VERSION=0.0.0
ARG DSA_WEB_REVISION=unknown

COPY apps/dsa-web/package.json apps/dsa-web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

COPY apps/dsa-web/ ./
RUN DSA_WEB_VERSION="${DSA_WEB_VERSION}" DSA_WEB_REVISION="${DSA_WEB_REVISION}" npm run build

# Pin to bookworm: wkhtmltopdf was removed from Debian testing (2025)
FROM python:3.11-slim-bookworm

# Working directory
WORKDIR /app

# Container time zone: US Eastern (New York and Toronto share it); SCHEDULE_TIME and the Web UI's "today" use it
ENV TZ=America/New_York
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# System packages (wkhtmltopdf ships wkhtmltoimage, used to render Markdown as images, issue #289)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    gosu \
    wkhtmltopdf \
    fontconfig \
    fonts-noto-cjk \
    libjpeg62-turbo \
    libxrender1 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user (UID 1000)
RUN groupadd -g 1000 dsa && \
    useradd -u 1000 -g dsa -m dsa

# Dependency manifests
COPY requirements.txt .

# Python dependencies
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

# Application code
COPY *.py ./
COPY api/ ./api/
COPY data_provider/ ./data_provider/
COPY bot/ ./bot/
COPY src/ ./src/
COPY strategies/ ./strategies/
COPY --from=web-builder /app/static ./static/
COPY docker/entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# Verify globally bundled runtime dependencies without leaving SDK logs in the image.
RUN mkdir -p /tmp/futu-sdk-smoke-home && \
    HOME=/tmp/futu-sdk-smoke-home python -c "import src.services.screening.pipeline; import futu" && \
    rm -rf /tmp/futu-sdk-smoke-home

# Create the data directories and hand them to the non-root user
RUN mkdir -p /app/data /app/logs /app/reports && \
    chown -R dsa:dsa /app && \
    chmod +x /usr/local/bin/docker-entrypoint.sh

# Environment defaults
ENV PYTHONUNBUFFERED=1
ENV LOG_DIR=/app/logs
ENV DATABASE_PATH=/app/data/stock_analysis.db
# Web/API service
ENV WEBUI_HOST=0.0.0.0
ENV API_PORT=8000

# API port
EXPOSE 8000

# Volumes (persistent data)
VOLUME ["/app/data", "/app/logs", "/app/reports"]

# Health check (FastAPI mode)
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || curl -f http://localhost:8000/health \
    || python -c "import sys; sys.exit(0)"

# The entrypoint fixes bind-mount directory ownership, then drops to the dsa user to run the app;
# documented docker-compose exec commands pass -u dsa so manual processes do not write root-owned files.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

# Default command (can be overridden)
CMD ["python", "main.py", "--schedule"]
