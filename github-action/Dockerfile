FROM python:3.12-slim

LABEL org.opencontainers.image.title="Tiramasu Repository Health"
LABEL org.opencontainers.image.description="Repository Health Intelligence scanner"

# Install system dependencies for tree-sitter compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Copy backend source
WORKDIR /ghostlint
COPY backend/ ./

# Install ghostlint and its dependencies
RUN uv pip install --system -e . --no-cache

# The repo to scan is mounted at /repo at runtime
WORKDIR /repo

COPY github-action/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
