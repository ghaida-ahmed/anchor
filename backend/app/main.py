"""ANCHOR API entry point."""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.endpoints import health
from app.api.v1.router import api_v1_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.rate_limit import (
    RateLimitExceededError,
    _client_key,
    baseline_limits,
    limiter,
)

DESCRIPTION = """
Backend for ANCHOR, an AI-powered adaptive learning platform.

**Phase 1** delivers the service foundation: configuration, database models and the
full API surface with its request/response contracts. `GET /api/health` is live.
Course, document and study-progress routes return `501 Not Implemented` until their
service layer is built — they never return placeholder data.
"""


_PROBE_PATHS = {f"{settings.API_PREFIX}/health", f"{settings.API_PREFIX}/ready"}


def create_app() -> FastAPI:
    configure_logging()
    """Application factory — keeps tests free to build their own instance."""
    app = FastAPI(
        title=settings.APP_NAME,
        description=DESCRIPTION,
        version="0.1.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _baseline_rate_limit(request: Request, call_next):
        """A floor under every route, including ones added later.

        Per-route `rate_limit_ai` handles the expensive endpoints; this catches
        everything else so a new route is never accidentally unlimited. Health and
        readiness are exempt: a platform polls them on a fixed schedule and must
        not be throttled into reporting the service down.

        The response is built here rather than raised, because an exception thrown
        inside middleware does not reach FastAPI's exception handlers.
        """
        if settings.RATE_LIMIT_ENABLED and request.url.path not in _PROBE_PATHS:
            bucket, limits = baseline_limits(request.method)
            try:
                limiter.check(_client_key(request, bucket), limits)
            except RateLimitExceededError as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content={"detail": str(exc)},
                    headers={"Retry-After": str(exc.retry_after)},
                )
        return await call_next(request)

    register_exception_handlers(app)

    # Unversioned: liveness probes should not care about the API version.
    app.include_router(health.router, prefix=settings.API_PREFIX)
    app.include_router(api_v1_router, prefix=f"{settings.API_PREFIX}/v1")

    return app


app = create_app()
