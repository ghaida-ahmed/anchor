# Production image for the ANCHOR API.
#
# Multi-stage so the wheel build toolchain does not ship in the runtime image:
# smaller to pull, and a compiler in a production container is a liability rather
# than a feature.
#
# Local development does not use this — `docker compose up` bind-mounts the source
# and runs uvicorn with --reload, which this image deliberately does not.

# --- build ------------------------------------------------------------------
FROM python:3.13-slim AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt

# --- runtime ----------------------------------------------------------------
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# psycopg[binary] bundles libpq, so no system postgres client is needed. curl is
# here only for the container healthcheck below.
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/*

# A non-root user: a container process that cannot write its own code cannot be
# made to persist a compromise there.
RUN useradd --create-home --uid 10001 anchor

WORKDIR /app

COPY --from=build /opt/venv /opt/venv
COPY --chown=anchor:anchor . .

# The storage root must exist and be writable before the app drops privileges.
# On a platform with an attached volume this is the mount point; without one it is
# ephemeral, which is why STORAGE_BACKEND is configuration — see README.
RUN mkdir -p /app/storage/documents && chown -R anchor:anchor /app/storage

USER anchor

# The host decides the port. Render, Fly and Cloud Run all inject $PORT and route
# to it; a hard-coded 8000 would work locally and then serve nothing in production.
ENV PORT=8000
EXPOSE 8000

# Uses the readiness route, not liveness: an orchestrator restarting a container
# whose database is briefly unreachable is the failure mode worth catching.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT}/api/ready" || exit 1

# Migrations are NOT run here. They are a separate, explicit step — see
# `docs/deployment.md`. Running them on every container start means a rollback or
# a scale-up silently mutates the schema, and two containers starting together
# race each other.
#
# One worker by default: the rate limiter keeps its counters in process memory, so
# additional workers would multiply the effective limits. Documented in the README.
# Shell form so ${PORT} is expanded at runtime. Exec form would pass the literal
# string "${PORT}" to uvicorn.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}" --workers 1
