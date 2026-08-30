from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Liveness. Deliberately minimal — it must not depend on anything."""

    status: str
    service: str


class ReadinessResponse(BaseModel):
    """Readiness, for a deployment platform's traffic decision.

    `ai_provider_configured` reports whether a key is *present*, never the key, and
    is informational only: it does not gate readiness, because every deterministic
    feature works without one.
    """

    status: str
    service: str
    environment: str
    database: bool
    ai_provider_configured: bool
