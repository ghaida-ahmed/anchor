"""Rate limiting.

The suite disables limits globally (see `rate_limits_off` in conftest) because
hundreds of requests from one TestClient address would otherwise make tests fail
by execution order. These tests turn them back on deliberately and assert the
behaviour that actually protects the deployment: the AI bucket.
"""

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import Limit, RateLimitExceededError, SlidingWindowLimiter
from app.tests.conftest import auth, make_topic, quiz_payload, unique_email

NOTES = (
    b"On detecting packet loss the congestion window is halved, draining the "
    b"bottleneck queue. Additive increase then probes for capacity again."
)


@pytest.fixture
def limits_on(monkeypatch: pytest.MonkeyPatch):
    """Re-enable limiting for one test, then hand back a clean limiter."""
    from app.core.rate_limit import limiter

    limiter.reset()
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    yield limiter
    limiter.reset()


class TestSlidingWindow:
    """The algorithm, tested without HTTP so the assertions are exact."""

    def test_requests_within_the_limit_pass(self) -> None:
        limiter = SlidingWindowLimiter()
        for _ in range(5):
            limiter.check("key", (Limit(count=5, window_seconds=60),))

    def test_the_request_over_the_limit_is_rejected(self) -> None:
        limiter = SlidingWindowLimiter()
        limits = (Limit(count=3, window_seconds=60),)
        for _ in range(3):
            limiter.check("key", limits)
        with pytest.raises(RateLimitExceededError):
            limiter.check("key", limits)

    def test_a_rejected_request_is_not_recorded(self) -> None:
        """Otherwise a client hammering a closed window pushes its own reset
        further away every time it retries."""
        limiter = SlidingWindowLimiter()
        limits = (Limit(count=2, window_seconds=60),)
        limiter.check("key", limits)
        limiter.check("key", limits)

        for _ in range(5):
            with pytest.raises(RateLimitExceededError) as caught:
                limiter.check("key", limits)

        # Still bounded by the ORIGINAL window, not pushed out by the retries.
        assert caught.value.retry_after <= 61

    def test_keys_are_independent(self) -> None:
        limiter = SlidingWindowLimiter()
        limits = (Limit(count=1, window_seconds=60),)
        limiter.check("student-a", limits)
        limiter.check("student-b", limits)

    def test_both_windows_apply(self) -> None:
        """A slow drip inside the per-minute limit still hits the hourly one."""
        limiter = SlidingWindowLimiter()
        limits = (Limit(count=10, window_seconds=60), Limit(count=3, window_seconds=3600))
        for _ in range(3):
            limiter.check("key", limits)
        with pytest.raises(RateLimitExceededError) as caught:
            limiter.check("key", limits)
        assert "hour" in str(caught.value)

    def test_retry_after_is_always_at_least_one_second(self) -> None:
        limiter = SlidingWindowLimiter()
        limits = (Limit(count=1, window_seconds=1),)
        limiter.check("key", limits)
        with pytest.raises(RateLimitExceededError) as caught:
            limiter.check("key", limits)
        assert caught.value.retry_after >= 1


class TestAiEndpointLimit:
    def test_ai_generation_is_limited_and_returns_429(
        self,
        client: TestClient,
        token: str,
        course_id: str,
        session: Session,
        llm,
        limits_on,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client.post(
            f"/api/v1/courses/{course_id}/documents",
            files={"file": ("notes.txt", io.BytesIO(NOTES), "text/plain")},
            headers=auth(token),
        )
        make_topic(
            session, course_id, "Congestion Control", "Halving the window on loss."
        )
        session.flush()
        llm.json_response = quiz_payload(3)

        # Two calls, so the third is over the limit regardless of ordering.
        monkeypatch.setattr(settings, "RATE_LIMIT_AI_PER_MINUTE", 2)
        from app.core import rate_limit as rl

        monkeypatch.setattr(
            rl.rate_limit_ai, "limits", (Limit(count=2, window_seconds=60),)
        )

        statuses = []
        for _ in range(4):
            response = client.post(
                f"/api/v1/courses/{course_id}/quizzes",
                json={"mode": "standard", "question_count": 3},
                headers=auth(token),
            )
            statuses.append(response.status_code)

        assert 429 in statuses, statuses
        first_429 = next(i for i, s in enumerate(statuses) if s == 429)
        # The limit bites only after the allowance is spent.
        assert first_429 >= 2

    def test_a_429_carries_retry_after(
        self, client: TestClient, token: str, limits_on, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.core import rate_limit as rl

        monkeypatch.setattr(
            rl.rate_limit_auth, "limits", (Limit(count=1, window_seconds=60),)
        )
        payload = {
            "name": "Rate Limited",
            "email": unique_email("ratelimit"),
            "password": "correct-horse-9",
        }
        client.post("/api/v1/auth/register", json=payload)
        second = client.post(
            "/api/v1/auth/register",
            json={**payload, "email": unique_email("ratelimit2")},
        )

        assert second.status_code == 429
        assert "Retry-After" in second.headers
        assert int(second.headers["Retry-After"]) >= 1
        assert "Too many requests" in second.json()["detail"]


class TestProbesAreExempt:
    def test_health_and_readiness_are_never_throttled(
        self, client: TestClient, limits_on, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A platform polls these on a fixed schedule. Throttling them would make
        the service report itself down under its own monitoring."""
        monkeypatch.setattr(settings, "RATE_LIMIT_READ_PER_MINUTE", 2)

        statuses = {client.get("/api/health").status_code for _ in range(20)}
        assert statuses == {200}

        ready = {client.get("/api/ready").status_code for _ in range(20)}
        assert ready <= {200, 503}
        assert 429 not in ready


class TestDisabledByConfiguration:
    def test_nothing_is_limited_when_the_flag_is_off(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
        statuses = {client.get("/api/health").status_code for _ in range(50)}
        assert statuses == {200}
