"""Liveness and readiness.

The two answer different questions and are deliberately separate:

* **liveness** — is the process up? Cheap, dependency-free, and safe to poll
  every few seconds. A platform restarts the container when this fails, so it
  must not fail because a *downstream* service is briefly unavailable.
* **readiness** — should traffic be routed here? Checks the database and the
  configuration the app cannot serve without.

Neither calls a language model. A health check that costs an API call is a health
check that bills you for being monitored, and would fail the whole deployment when
a provider has an outage the application is designed to survive.
"""

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine
from app.schemas import HealthResponse, ReadinessResponse

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse, summary="Service liveness check")
def health() -> HealthResponse:
    """Answers without touching the database, so it stays a true liveness probe."""
    return HealthResponse(status="ok", service=settings.APP_NAME)


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness check for deployment",
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Not ready to serve."}
    },
)
def ready(response: Response) -> ReadinessResponse:
    """Verify the dependencies a request actually needs.

    Returns 503 when the database is unreachable, so a load balancer stops sending
    traffic instead of serving 500s. The AI provider is reported but never gates
    readiness: without a key the app still serves courses, uploads and every
    deterministic feature — only generation refuses, with its own 503.
    """
    database_ok = True
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        # Deliberately no exception text: it carries the connection string.
        database_ok = False

    ready_now = database_ok
    if not ready_now:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        status="ready" if ready_now else "not_ready",
        service=settings.APP_NAME,
        environment=settings.ENVIRONMENT,
        database=database_ok,
        # Whether a key is configured — never the key, and no call is made.
        ai_provider_configured=bool(
            settings.GEMINI_API_KEY
            if settings.AI_PROVIDER == "gemini"
            else settings.OPENAI_API_KEY
        ),
    )
