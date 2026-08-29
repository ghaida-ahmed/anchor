"""Effective mastery: the decay heuristic, and the guarantee that stored evidence
is never mutated by the passage of time."""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.clock import ensure_utc, frozen_time, now
from app.services.learning.retention import (
    BASE_HALF_LIFE_DAYS,
    FLOOR,
    days_since_practice,
    effective_mastery,
    half_life_days,
    retention_status,
)

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def after(days: float) -> datetime:
    return T0 + timedelta(days=days)


class TestDocumentedExamples:
    """The exact figures published in the README and the module docstring."""

    @pytest.mark.parametrize(
        ("stored", "evidence", "days", "expected"),
        [
            (80, 5, 1, 79.3),
            (80, 5, 30, 64.0),
            (80, 5, 60, 55.1),
            (50, 2, 30, 35.9),
            (25, 1, 30, 16.6),
        ],
    )
    def test_worked_examples(
        self, stored: float, evidence: float, days: int, expected: float
    ) -> None:
        result = effective_mastery(stored, evidence, T0, at=after(days))

        assert result == pytest.approx(expected, abs=0.05)


class TestProperties:
    def test_no_elapsed_time_returns_stored_mastery_exactly(self) -> None:
        assert effective_mastery(80.0, 5, T0, at=T0) == pytest.approx(80.0)

    def test_decay_never_increases_mastery(self) -> None:
        """Inactivity must never look like progress."""
        previous = 80.0
        for day in range(0, 400, 7):
            current = effective_mastery(80.0, 5, T0, at=after(day))
            assert current <= previous + 1e-9
            previous = current

    def test_decay_is_monotonic(self) -> None:
        values = [effective_mastery(80.0, 5, T0, at=after(d)) for d in range(0, 200, 5)]
        assert values == sorted(values, reverse=True)

    def test_score_stays_within_bounds(self) -> None:
        for stored in (0.0, 1.0, 50.0, 99.9, 100.0):
            for days in (0, 1, 30, 365, 10_000):
                value = effective_mastery(stored, 5, T0, at=after(days))
                assert 0.0 <= value <= 100.0

    def test_decay_asymptotes_at_the_floor(self) -> None:
        """Neglect raises doubt; it does not erase a demonstrated result."""
        far_future = effective_mastery(80.0, 5, T0, at=after(100_000))

        assert far_future == pytest.approx(80.0 * FLOOR, abs=0.1)

    def test_no_evidence_yields_zero(self) -> None:
        assert effective_mastery(0.0, 0, None, at=after(30)) == 0.0

    def test_evidence_but_no_timestamp_is_not_decayed(self) -> None:
        """Rather than inventing an elapsed time for an impossible state."""
        assert effective_mastery(70.0, 5, None, at=after(90)) == pytest.approx(70.0)


class TestEvidenceAndStrength:
    def test_more_evidence_decays_more_slowly(self) -> None:
        thin = effective_mastery(60.0, 1, T0, at=after(30))
        thick = effective_mastery(60.0, 20, T0, at=after(30))

        assert thick > thin

    def test_stronger_knowledge_decays_more_slowly(self) -> None:
        """Compared as a proportion of what was demonstrated."""
        weak_ratio = effective_mastery(30.0, 5, T0, at=after(30)) / 30.0
        strong_ratio = effective_mastery(90.0, 5, T0, at=after(30)) / 90.0

        assert strong_ratio > weak_ratio

    def test_half_life_bounds(self) -> None:
        smallest = half_life_days(0.0, 0)
        largest = half_life_days(100.0, 100)

        assert smallest == pytest.approx(BASE_HALF_LIFE_DAYS * 0.5 * 0.7)
        assert largest == pytest.approx(BASE_HALF_LIFE_DAYS * 1.0 * 1.3)
        assert smallest < largest


class TestStoredMasteryIsNeverMutated:
    def test_decay_is_a_pure_read(self, client, token, course_id, session) -> None:
        """The headline guarantee: no job subtracts points as time passes."""
        from app.models import TopicMastery
        from app.tests.conftest import make_topic

        topic = make_topic(session, course_id, "Retention Topic")
        session.flush()

        me = client.get(
            "/api/v1/auth/me",
            headers=__import__("app.tests.conftest", fromlist=["auth"]).auth(token),
        ).json()
        import uuid as _uuid

        row = TopicMastery(
            user_id=_uuid.UUID(me["id"]),
            course_id=course_id,
            topic_id=topic.id,
            raw_score=82.0,
            mastery_score=82.0,
            questions_attempted=8,
            correct_answers=7,
            last_practised_at=T0,
        )
        session.add(row)
        session.flush()

        # Read it far in the future.
        with frozen_time(after(60)):
            estimate = effective_mastery(
                row.mastery_score, 8, row.last_practised_at, at=now()
            )

        session.refresh(row)
        assert row.mastery_score == 82.0, "stored evidence must be untouched"
        assert row.raw_score == 82.0
        assert estimate < 82.0


class TestTimezoneSafety:
    def test_naive_timestamps_are_coerced_not_compared(self) -> None:
        """A naive datetime from a fixture or driver must not raise."""
        naive = datetime(2026, 1, 1, 12, 0)

        result = effective_mastery(80.0, 5, naive, at=after(30))

        assert result == pytest.approx(64.0, abs=0.1)

    def test_ensure_utc_normalises(self) -> None:
        assert ensure_utc(datetime(2026, 1, 1)).tzinfo is UTC

    def test_days_since_practice_never_negative(self) -> None:
        """A clock skew must not produce negative elapsed time."""
        assert days_since_practice(after(10), at=T0) == 0.0

    def test_frozen_time_restores_the_previous_value(self) -> None:
        outer = now()
        with frozen_time(T0):
            assert now() == T0
            with frozen_time(after(5)):
                assert now() == after(5)
            assert now() == T0
        assert now() != T0 or outer == T0


class TestRetentionStatus:
    def test_no_evidence_is_new_not_overdue(self) -> None:
        assert retention_status(has_evidence=False, days_since_practice=None) == "new"

    def test_overdue_cards_dominate(self) -> None:
        status = retention_status(
            has_evidence=True, days_since_practice=1.0, due_cards=3, overdue_cards=2
        )
        assert status == "overdue"

    def test_due_cards_outrank_elapsed_time(self) -> None:
        status = retention_status(has_evidence=True, days_since_practice=1.0, due_cards=1)
        assert status == "due"

    def test_long_gap_flags_review_soon(self) -> None:
        assert (
            retention_status(has_evidence=True, days_since_practice=20.0) == "review_soon"
        )

    def test_recent_practice_is_fresh(self) -> None:
        assert retention_status(has_evidence=True, days_since_practice=1.0) == "fresh"

    def test_status_is_independent_of_attainment(self) -> None:
        """A Strong topic can still be due — the two ideas must not be conflated."""
        assert (
            retention_status(has_evidence=True, days_since_practice=40.0) == "review_soon"
        )
