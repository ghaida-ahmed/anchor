"""Flashcard review scheduling — the ANCHOR heuristic.

This is NOT FSRS, and does not claim to be. FSRS is a fitted model with published
parameters and a memory-state formulation; implementing a rough approximation and
borrowing the name would misrepresent it. What follows is a deterministic
interval-multiplier scheme in the SM-2 tradition, chosen because it is small enough
to explain in a paragraph and to test exhaustively.

THE ALGORITHM
=============

Per (user, card) we keep an interval in days and an ease multiplier.

    ease starts at 2.5, clamped to [1.30, 3.00]
    intervals clamped to [1, 365] days after the first success

    AGAIN   interval -> 0, due in RELEARN_MINUTES     ease -= 0.20   lapse recorded
    HARD    interval -> max(1, round(base * 1.2))     ease -= 0.15
    GOOD    1st: 1 day   2nd: 3 days   then round(base * ease)
    EASY    1st: 3 days                then round(base * ease * 1.3)  ease += 0.15

OVERDUE CREDIT
--------------

Recalling a card that is a fortnight late is stronger evidence than recalling one
reviewed exactly on time, so for GOOD and EASY the next interval is computed from

    base = min(elapsed_days, previous_interval * 2)

rather than from the scheduled interval. Bounding it at twice the previous interval
stops one very overdue success from launching a card years into the future.

WORKED EXAMPLES
---------------

    new -> Good                      1 day
    new -> Easy                      3 days
    Good, Good, Good                 1, 3, 8 days
    Good then Again                  1 day, then 10 minutes (ease 2.50 -> 2.30)
    interval 10, 30 days overdue, Good   base=20 -> 50 days
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.clock import days_between, now
from app.models.flashcard_review import ReviewRating

INITIAL_EASE = 2.5
MIN_EASE = 1.3
MAX_EASE = 3.0

MIN_INTERVAL_DAYS = 1
MAX_INTERVAL_DAYS = 365

# A failed card comes back within the same session rather than the same day: the
# point of Again is immediate relearning.
RELEARN_MINUTES = 10

FIRST_GOOD_DAYS = 1
SECOND_GOOD_DAYS = 3
FIRST_EASY_DAYS = 3

HARD_MULTIPLIER = 1.2
EASY_BONUS = 1.3

EASE_AGAIN = -0.20
EASE_HARD = -0.15
EASE_EASY = 0.15

# Overdue credit is capped at this multiple of the scheduled interval.
MAX_OVERDUE_CREDIT = 2.0


@dataclass(frozen=True)
class ScheduleState:
    """Everything the scheduler reads and writes for one card."""

    interval_days: int = 0
    ease: float = INITIAL_EASE
    review_count: int = 0
    success_count: int = 0
    lapses: int = 0
    last_reviewed_at: datetime | None = None
    due_at: datetime | None = None

    @property
    def is_new(self) -> bool:
        return self.review_count == 0


NEW_CARD = ScheduleState()


def schedule(
    state: ScheduleState,
    rating: ReviewRating,
    *,
    at: datetime | None = None,
) -> ScheduleState:
    """Apply one review. Pure, deterministic, total.

    `at` is the review instant; it defaults to the shared clock so tests can drive
    a timeline without patching anything.
    """
    reviewed_at = at or now()
    elapsed = (
        days_between(state.last_reviewed_at, reviewed_at)
        if state.last_reviewed_at is not None
        else 0.0
    )

    ease = state.ease
    interval = state.interval_days
    lapses = state.lapses
    successes = state.success_count

    if rating is ReviewRating.AGAIN:
        ease = _clamp_ease(ease + EASE_AGAIN)
        lapses += 1
        # Relearning: the card returns within minutes, and its interval resets so
        # the next success starts the ladder again rather than resuming where it
        # left off.
        return ScheduleState(
            interval_days=0,
            ease=ease,
            review_count=state.review_count + 1,
            success_count=successes,
            lapses=lapses,
            last_reviewed_at=reviewed_at,
            due_at=reviewed_at + timedelta(minutes=RELEARN_MINUTES),
        )

    successes += 1

    if rating is ReviewRating.HARD:
        ease = _clamp_ease(ease + EASE_HARD)
        base = max(interval, MIN_INTERVAL_DAYS)
        interval = _clamp_interval(round(base * HARD_MULTIPLIER))
    elif rating is ReviewRating.GOOD:
        if interval <= 0:
            interval = FIRST_GOOD_DAYS
        elif interval < SECOND_GOOD_DAYS:
            interval = SECOND_GOOD_DAYS
        else:
            interval = _clamp_interval(round(_credited(interval, elapsed) * ease))
    else:  # EASY
        ease = _clamp_ease(ease + EASE_EASY)
        if interval <= 0:
            interval = FIRST_EASY_DAYS
        else:
            interval = _clamp_interval(
                round(_credited(interval, elapsed) * ease * EASY_BONUS)
            )

    return ScheduleState(
        interval_days=interval,
        ease=ease,
        review_count=state.review_count + 1,
        success_count=successes,
        lapses=lapses,
        last_reviewed_at=reviewed_at,
        # Whole days from the review instant. Never in the past, by construction.
        due_at=reviewed_at + timedelta(days=interval),
    )


def describe_interval(state: ScheduleState) -> str:
    """Student-facing wording for the next review, e.g. "in 3 days".

    Deliberately vague about the internals: the student needs to know when to come
    back, not the ease factor.
    """
    if state.interval_days <= 0:
        return "in a few minutes"
    if state.interval_days == 1:
        return "tomorrow"
    if state.interval_days < 30:
        return f"in {state.interval_days} days"
    months = round(state.interval_days / 30)
    return f"in about {months} month{'s' if months > 1 else ''}"


def _credited(interval: int, elapsed_days: float) -> float:
    """Reward a successful late recall, bounded at twice the scheduled interval."""
    if elapsed_days <= interval:
        return float(interval)
    return min(elapsed_days, interval * MAX_OVERDUE_CREDIT)


def _clamp_ease(value: float) -> float:
    return max(MIN_EASE, min(MAX_EASE, round(value, 4)))


def _clamp_interval(value: float) -> int:
    return int(max(MIN_INTERVAL_DAYS, min(MAX_INTERVAL_DAYS, value)))
