# Base ships Playwright + Chromium preinstalled. If image > 1.2 GB,
# switch to `pyd4vinci/scrapling:slim`.
FROM pyd4vinci/scrapling:latest

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Build context must be the monorepo root: `pyproject.toml` references
# `../../packages/sse-protocol/generated/python` as an editable workspace
# dep that must be on disk before `uv sync`.
#   Local:  `docker build -t autumn-api -f apps/api/Dockerfile .`
#   Fly:    `fly deploy --config apps/api/fly.toml` from the repo root.
WORKDIR /app

# Layer caching: deps before code so code-only changes reuse the resolver.
COPY packages/sse-protocol/generated/python /app/packages/sse-protocol/generated/python
COPY apps/api/pyproject.toml apps/api/uv.lock /app/apps/api/

WORKDIR /app/apps/api
RUN uv sync --frozen --no-dev --no-install-project

COPY apps/api/app ./app
COPY apps/api/alembic ./alembic
COPY apps/api/alembic.ini ./

RUN uv sync --frozen --no-dev --no-editable

EXPOSE 8000

# `--workers 1` is load-bearing: the lifespan TaskGroup (invariant 3) is
# process-local. Multi-worker requires inter-process coordination of the
# SSE emitter and runner registry — out of scope for MVP.
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
