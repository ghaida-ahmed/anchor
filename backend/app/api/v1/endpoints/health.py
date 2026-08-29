from fastapi import APIRouter

from app.core.config import settings
from app.schemas import HealthResponse

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse, summary="Service liveness check")
def health() -> HealthResponse:
    """Answers without touching the database, so it stays a true liveness probe."""
    return HealthResponse(status="ok", service=settings.APP_NAME)
