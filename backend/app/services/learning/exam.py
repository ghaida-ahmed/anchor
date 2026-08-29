"""Exam Readiness and exam-mode topic priority.

Both are deterministic functions of the mastery table and the review queue. No model
is consulted: "how ready am I?" is a question the data already answers, and an
answer that changed between refreshes would be worse than useless.

EXAM READINESS
==============

    readiness = 100 x ( 0.60 * mean_effective_mastery
                      + 0.25 * coverage
                      + 0.15 * review_currency )

    mean_effective_mastery = mean(effective mastery) over ALL active topics,
                             counting never-practised topics as 0
    coverage               = started topics / active topics
    review_currency        = 1 - min(1, overdue_cards / max(1, total_cards))

Unpractised topics are punished twice, deliberately: once by dragging the mean down
and once through coverage. For an exam both depth and breadth matter, and a student
who has mastered one topic of five is not 100% ready for anything.

    5 of 5 topics at 60% effective, nothing overdue  ->  76
    1 of 5 topics at 100% effective, nothing overdue ->  32
    nothing practised at all                         ->   0

THIS IS NOT A PREDICTED GRADE. It is an indicator built from practice evidence. It
knows nothing about the exam's content, weighting or difficulty, and it should never
be presented as a forecast of a result.

EXAM-MODE PRIORITY
==================

Ordinary adaptive practice optimises for learning; exam practice optimises for
coverage under a deadline. The weights change accordingly:

    exam_priority = 0.50 * weakness        (from effective mastery)
                  + 0.30 * coverage_gap    1 if never practised, else 0
                  + 0.20 * recent_miss

`evidence_need` is replaced by the blunter `coverage_gap`, because with days left
the question is "have I touched this at all?" rather than "how well established is
it?".

Urgency does not scale priorities — multiplying every topic by the same factor
would not reorder anything. Instead, as the exam approaches ANCHOR widens each
session to cover more topics, and shifts difficulty upward once the exam is close
enough that exam-realistic questions matter more than gentle progression. Both
changes are bounded, so nothing lurches on the final day.
"""

from dataclasses import dataclass
from datetime import date

from app.services.learning.adaptive import TopicCandidate
from app.services.learning.mastery import DEVELOPING, NEEDS_PRACTICE, NOT_STARTED, STRONG

W_EXAM_MASTERY = 0.60
W_EXAM_COVERAGE = 0.25
W_EXAM_CURRENCY = 0.15

W_EXAM_WEAKNESS = 0.50
W_EXAM_COVERAGE_GAP = 0.30
W_EXAM_RECENT_MISS = 0.20

# Topics per exam-prep session: 3 when the exam is distant, rising to 6 as it nears.
MIN_EXAM_TOPICS = 3
MAX_EXAM_TOPICS = 6
# Horizon over which sessions widen. Beyond this, exam mode behaves like normal
# adaptive practice in breadth.
WIDENING_HORIZON_DAYS = 21.0
# Inside this many days, difficulty shifts up one band to be exam-realistic.
HARDENING_WINDOW_DAYS = 7


@dataclass(frozen=True)
class ReadinessBreakdown:
    """The score plus its parts, so the UI can explain rather than assert."""

    readiness: float
    mean_effective_mastery: float
    coverage: float
    review_currency: float
    topics_total: int
    topics_started: int
    overdue_cards: int
    total_cards: int


def exam_readiness(
    candidates: list[TopicCandidate],
    *,
    overdue_cards: int = 0,
    total_cards: int = 0,
) -> ReadinessBreakdown:
    """Compute the readiness indicator over a course's active topics."""
    if not candidates:
        return ReadinessBreakdown(0.0, 0.0, 0.0, 1.0, 0, 0, overdue_cards, total_cards)

    started = [c for c in candidates if c.state.has_evidence]
    mean_effective = sum(c.effective_mastery for c in candidates) / len(candidates)
    coverage = len(started) / len(candidates)
    currency = 1.0 - min(1.0, overdue_cards / max(1, total_cards)) if total_cards else 1.0

    if not started:
        # Nothing practised is not partial readiness. Without this, the review
        # currency term would award marks for having no cards overdue, which is
        # trivially true for a student who has done nothing at all.
        readiness = 0.0
    else:
        readiness = 100.0 * (
            W_EXAM_MASTERY * (mean_effective / 100.0)
            + W_EXAM_COVERAGE * coverage
            + W_EXAM_CURRENCY * currency
        )

    return ReadinessBreakdown(
        readiness=_clamp(readiness),
        mean_effective_mastery=round(mean_effective, 1),
        coverage=round(coverage, 4),
        review_currency=round(currency, 4),
        topics_total=len(candidates),
        topics_started=len(started),
        overdue_cards=overdue_cards,
        total_cards=total_cards,
    )


def exam_priority(candidate: TopicCandidate) -> float:
    """Practice priority under exam conditions, in [0, 1]."""
    weakness = (100.0 - candidate.effective_mastery) / 100.0
    coverage_gap = 0.0 if candidate.state.has_evidence else 1.0
    recent_miss = 1.0 if candidate.state.last_answer_correct is False else 0.0

    return (
        W_EXAM_WEAKNESS * weakness
        + W_EXAM_COVERAGE_GAP * coverage_gap
        + W_EXAM_RECENT_MISS * recent_miss
    )


def topics_for_session(days_remaining: int | None, available: int) -> int:
    """How many topics one exam-prep session should span.

    Widens smoothly as the exam approaches, bounded at both ends so the day before
    the exam is not qualitatively different from two days before.
    """
    if available <= 0:
        return 0
    if days_remaining is None:
        return min(MIN_EXAM_TOPICS, available)

    remaining = max(0, days_remaining)
    nearness = 1.0 - min(1.0, remaining / WIDENING_HORIZON_DAYS)
    span = MIN_EXAM_TOPICS + round(nearness * (MAX_EXAM_TOPICS - MIN_EXAM_TOPICS))
    return min(span, available)


def harden_band(band: str, days_remaining: int | None) -> str:
    """Shift a topic one band up once the exam is close.

    Close to an exam, practising only easy recall is a poor use of the time left;
    the student needs questions resembling the paper. Applied once, never twice, so
    a weak topic never jumps straight to hard questions.
    """
    if days_remaining is None or days_remaining > HARDENING_WINDOW_DAYS:
        return band

    return {
        NOT_STARTED: NEEDS_PRACTICE,
        NEEDS_PRACTICE: DEVELOPING,
        DEVELOPING: STRONG,
        STRONG: STRONG,
    }.get(band, band)


def days_until(exam_date: date | None, today: date) -> int | None:
    """Whole days from `today` to the exam. Negative once it has passed."""
    if exam_date is None:
        return None
    return (exam_date - today).days


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))
