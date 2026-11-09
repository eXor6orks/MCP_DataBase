# syntax=docker/dockerfile:1

# ---- Stage 1 : builder ----
FROM python:3.14-slim as builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Étape 1 : installer les dépendances seules (cache réutilisé tant que
# pyproject.toml/uv.lock ne changent pas, même si le code source change)
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Étape 2 : installer le projet lui-même, avec le code source
COPY src/ ./src/
COPY config/ ./config/
COPY README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---- Stage 2 : runtime ----
FROM python:3.14-slim AS runtime

RUN useradd --create-home --uid 1000 mcpuser
WORKDIR /app

COPY --from=builder --chown=mcpuser:mcpuser /app/.venv /app/.venv
COPY --from=builder --chown=mcpuser:mcpuser /app/src /app/src
COPY --from=builder --chown=mcpuser:mcpuser /app/config /app/config

ENV PATH="/app/.venv/bin:$PATH"
USER mcpuser

EXPOSE 8000
CMD ["python", "src/mcp_db_server/server.py"]