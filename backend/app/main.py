"""ANCHOR API entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.endpoints import health
from app.api.v1.router import api_v1_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers

DESCRIPTION = """
Backend for ANCHOR, an AI-powered adaptive learning platform.

**Phase 1** delivers the service foundation: configuration, database models and the
full API surface with its request/response contracts. `GET /api/health` is live.
Course, document and study-progress routes return `501 Not Implemented` until their
service layer is built — they never return placeholder data.
"""


def create_app() -> FastAPI:
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

    register_exception_handlers(app)

    # Unversioned: liveness probes should not care about the API version.
    app.include_router(health.router, prefix=settings.API_PREFIX)
    app.include_router(api_v1_router, prefix=f"{settings.API_PREFIX}/v1")

    return app


app = create_app()
