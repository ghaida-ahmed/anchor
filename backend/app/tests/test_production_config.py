"""Production configuration must fail fast rather than start unsafely.

Every case here is a misconfiguration that is silent at startup and expensive
later: a forgeable token, a debug traceback in a log, a CORS wildcard letting any
origin spend a student's API quota. The application refuses to boot on each.
"""

import pytest

from app.core.config import _DEV_DATABASE_URL, _DEV_SECRET, Settings

# A configuration that should be accepted, used as the base for each negative case
# so exactly one thing is wrong at a time.
VALID = {
    "ENVIRONMENT": "production",
    "DEBUG": False,
    "SECRET_KEY": "d" * 48,
    "DATABASE_URL": "postgresql+psycopg://user:pw@db.example.com:5432/anchor",
    "CORS_ORIGINS": ["https://anchor.example.com"],
}


def build(**overrides) -> Settings:
    """Build settings from an explicit dict, ignoring any local .env file.

    `_env_file=None` matters: without it a developer's real .env would leak into
    these assertions and the test would pass or fail based on their machine.
    """
    return Settings(_env_file=None, **{**VALID, **overrides})


class TestProductionRejects:
    def test_a_valid_production_config_is_accepted(self) -> None:
        settings = build()
        assert settings.is_production
        assert not settings.DEBUG

    def test_debug_is_refused(self) -> None:
        with pytest.raises(ValueError, match="DEBUG"):
            build(DEBUG=True)

    def test_the_development_database_is_refused(self) -> None:
        """Its credentials are published in the README."""
        with pytest.raises(ValueError, match="DATABASE_URL"):
            build(DATABASE_URL=_DEV_DATABASE_URL)

    def test_the_shared_development_secret_is_refused(self) -> None:
        with pytest.raises(ValueError, match="SECRET_KEY"):
            build(SECRET_KEY=_DEV_SECRET)

    def test_a_blank_secret_is_refused(self) -> None:
        with pytest.raises(ValueError, match="SECRET_KEY"):
            build(SECRET_KEY="")

    def test_a_short_secret_is_refused(self) -> None:
        """Under 32 characters is below the RFC 7518 floor for HS256."""
        with pytest.raises(ValueError, match="at least 32"):
            build(SECRET_KEY="a" * 31)

    def test_wildcard_cors_is_refused(self) -> None:
        with pytest.raises(ValueError, match=r"CORS_ORIGINS contains '\*'"):
            build(CORS_ORIGINS=["*"])

    def test_empty_cors_is_refused(self) -> None:
        with pytest.raises(ValueError, match="CORS_ORIGINS is empty"):
            build(CORS_ORIGINS=[])

    def test_a_plaintext_origin_is_refused(self) -> None:
        """Bearer tokens would travel unencrypted."""
        with pytest.raises(ValueError, match="http://"):
            build(CORS_ORIGINS=["http://anchor.example.com"])

    def test_localhost_over_http_is_still_allowed(self) -> None:
        """Useful for a production build pointed at a local API while debugging;
        the traffic never leaves the machine."""
        settings = build(CORS_ORIGINS=["http://localhost:5173"])
        assert settings.CORS_ORIGINS == ["http://localhost:5173"]

    def test_staging_is_held_to_the_same_rules(self) -> None:
        """A staging box on the public internet with a dev secret is still a
        forgeable-token box."""
        with pytest.raises(ValueError):
            build(ENVIRONMENT="staging", SECRET_KEY=_DEV_SECRET)


class TestDevelopmentStaysConvenient:
    def test_development_tolerates_a_blank_secret(self) -> None:
        """It falls back to the shared dev secret so the app still starts."""
        settings = Settings(_env_file=None, ENVIRONMENT="development", SECRET_KEY="")
        assert settings.SECRET_KEY == _DEV_SECRET

    def test_development_tolerates_the_local_database(self) -> None:
        settings = Settings(
            _env_file=None,
            ENVIRONMENT="development",
            DATABASE_URL=_DEV_DATABASE_URL,
            DEBUG=True,
        )
        assert not settings.is_production

    def test_an_error_message_never_contains_the_secret(self) -> None:
        """Config errors reach logs, and a log is a place secrets escape from."""
        secret = "a-real-looking-production-secret-value-0123456789"
        with pytest.raises(ValueError) as caught:
            build(SECRET_KEY=secret, DEBUG=True)
        assert secret not in str(caught.value)
