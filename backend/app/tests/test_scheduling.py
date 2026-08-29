"""The flashcard scheduling heuristic. Pure functions, so exact assertions."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models import ReviewRating
from app.services.learning.scheduling import (
    INITIAL_EASE,
    MAX_EASE,
    MAX_INTERVAL_DAYS,
    MIN_EASE,
    MIN_INTERVAL_DAYS,
    NEW_CARD,
    RELEARN_MINUTES,
    ScheduleState,
    describe_interval,
    schedule,
)

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def at(days: float) -> datetime:
    return T0 + timedelta(days=days)


class TestFirstReview:
    def test_new_card_good(self) -> None:
        state = schedule(NEW_CARD, ReviewRating.GOOD, at=T0)

        assert state.interval_days == 1
        assert state.due_at == T0 + timedelta(days=1)
        assert state.review_count == 1
        assert state.success_count == 1

    def test_new_card_easy(self) -> None:
        assert schedule(NEW_CARD, ReviewRating.EASY, at=T0).interval_days == 3

    def test_new_card_hard(self) -> None:
        assert schedule(NEW_CARD, ReviewRating.HARD, at=T0).interval_days >= 1

    def test_new_card_again_relearns_within_the_session(self) -> None:
        state = schedule(NEW_CARD, ReviewRating.AGAIN, at=T0)

        assert state.interval_days == 0
        assert state.due_at == T0 + timedelta(minutes=RELEARN_MINUTES)
        assert state.lapses == 1
        assert state.success_count == 0


class TestProgression:
    def test_repeated_good_grows_the_interval(self) -> None:
        state = NEW_CARD
        intervals = []
        elapsed = 0.0
        for _ in range(4):
            state = schedule(state, ReviewRating.GOOD, at=at(elapsed))
            intervals.append(state.interval_days)
            elapsed += state.interval_days

        assert intervals[:3] == [1, 3, 8]
        assert intervals == sorted(intervals)

    def test_easy_grows_faster_than_good(self) -> None:
        base = ScheduleState(
            interval_days=10,
            ease=INITIAL_EASE,
            review_count=3,
            success_count=3,
            last_reviewed_at=T0,
        )
        good = schedule(base, ReviewRating.GOOD, at=at(10))
        easy = schedule(base, ReviewRating.EASY, at=at(10))

        assert easy.interval_days > good.interval_days

    def test_hard_grows_slower_than_good(self) -> None:
        base = ScheduleState(
            interval_days=10,
            ease=INITIAL_EASE,
            review_count=3,
            success_count=3,
            last_reviewed_at=T0,
        )
        hard = schedule(base, ReviewRating.HARD, at=at(10))
        good = schedule(base, ReviewRating.GOOD, at=at(10))

        assert hard.interval_days < good.interval_days

    def test_failure_after_success_resets_the_ladder(self) -> None:
        state = schedule(NEW_CARD, ReviewRating.GOOD, at=T0)
        state = schedule(state, ReviewRating.GOOD, at=at(1))
        assert state.interval_days == 3

        failed = schedule(state, ReviewRating.AGAIN, at=at(4))
        assert failed.interval_days == 0

        recovered = schedule(failed, ReviewRating.GOOD, at=at(4))
        assert recovered.interval_days == 1, "relearning starts the ladder again"


class TestEase:
    def test_again_lowers_ease(self) -> None:
        assert schedule(NEW_CARD, ReviewRating.AGAIN, at=T0).ease < INITIAL_EASE

    def test_easy_raises_ease(self) -> None:
        assert schedule(NEW_CARD, ReviewRating.EASY, at=T0).ease > INITIAL_EASE

    def test_ease_is_clamped_at_the_bottom(self) -> None:
        state = NEW_CARD
        for index in range(30):
            state = schedule(state, ReviewRating.AGAIN, at=at(index))
        assert state.ease == MIN_EASE

    def test_ease_is_clamped_at_the_top(self) -> None:
        state = NEW_CARD
        elapsed = 0.0
        for _ in range(30):
            state = schedule(state, ReviewRating.EASY, at=at(elapsed))
            elapsed += state.interval_days
        assert state.ease == MAX_EASE


class TestOverdue:
    def test_late_success_earns_a_longer_interval(self) -> None:
        base = ScheduleState(
            interval_days=10,
            ease=INITIAL_EASE,
            review_count=3,
            success_count=3,
            last_reviewed_at=T0,
        )
        on_time = schedule(base, ReviewRating.GOOD, at=at(10))
        late = schedule(base, ReviewRating.GOOD, at=at(30))

        assert late.interval_days > on_time.interval_days
        assert late.interval_days == 50  # base = min(30, 10*2) = 20; 20 * 2.5

    def test_overdue_credit_is_bounded(self) -> None:
        """One very late success must not launch a card years ahead."""
        base = ScheduleState(
            interval_days=10,
            ease=INITIAL_EASE,
            review_count=3,
            success_count=3,
            last_reviewed_at=T0,
        )
        absurd = schedule(base, ReviewRating.GOOD, at=at(1000))

        assert absurd.interval_days == 50

    def test_overdue_failure_gets_no_credit(self) -> None:
        base = ScheduleState(
            interval_days=10,
            ease=INITIAL_EASE,
            review_count=3,
            success_count=3,
            last_reviewed_at=T0,
        )
        assert schedule(base, ReviewRating.AGAIN, at=at(90)).interval_days == 0


class TestBounds:
    def test_intervals_never_exceed_the_maximum(self) -> None:
        state = NEW_CARD
        elapsed = 0.0
        for _ in range(40):
            state = schedule(state, ReviewRating.EASY, at=at(elapsed))
            elapsed += state.interval_days
            assert state.interval_days <= MAX_INTERVAL_DAYS

    def test_successful_intervals_are_at_least_one_day(self) -> None:
        for rating in (ReviewRating.HARD, ReviewRating.GOOD, ReviewRating.EASY):
            assert schedule(NEW_CARD, rating, at=T0).interval_days >= MIN_INTERVAL_DAYS

    def test_due_dates_are_never_in_the_past(self) -> None:
        state = NEW_CARD
        elapsed = 0.0
        for index, rating in enumerate(
            [ReviewRating.GOOD, ReviewRating.AGAIN, ReviewRating.HARD, ReviewRating.EASY]
            * 5
        ):
            moment = at(elapsed + index)
            state = schedule(state, rating, at=moment)
            assert state.due_at is not None
            assert state.due_at >= moment


class TestDeterminism:
    def test_identical_inputs_give_identical_output(self) -> None:
        base = ScheduleState(
            interval_days=7,
            ease=2.3,
            review_count=4,
            success_count=3,
            last_reviewed_at=T0,
        )
        results = {
            schedule(base, ReviewRating.GOOD, at=at(9)).interval_days for _ in range(10)
        }
        assert len(results) == 1


class TestWording:
    @pytest.mark.parametrize(
        ("days", "expected"),
        [
            (0, "in a few minutes"),
            (1, "tomorrow"),
            (3, "in 3 days"),
            (60, "in about 2 months"),
        ],
    )
    def test_student_facing_labels(self, days: int, expected: str) -> None:
        state = ScheduleState(interval_days=days)
        assert describe_interval(state) == expected
