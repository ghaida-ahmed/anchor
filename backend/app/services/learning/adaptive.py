"""Deciding WHAT a student should practise, and at WHAT difficulty.

Pure functions, deterministic, no language model. This is the line that makes
ANCHOR adaptive rather than merely AI-powered:

    the backend decides what to practise and how hard;
    Gemini only writes grounded questions about what it was given.

Asking a model "what should this student study?" would be non-reproducible,
unexplainable, and would cost an API call to answer a question the mastery table
already answers exactly.

TOPIC SELECTION
===============

Every topic gets a priority in [0, 1]:

    priority = 0.50 * weakness
             + 0.25 * evidence_need
             + 0.15 * recent_miss
             + 0.10 * review_pressure

    weakness        = (100 - EFFECTIVE mastery) / 100
    evidence_need   = 1 - min(1, evidence / MIN_EVIDENCE)
    recent_miss     = 1 if the last answer on this topic was wrong else 0
    review_pressure = min(1, due_cards / REVIEW_PRESSURE_FULL)

WHY STALENESS IS GONE
---------------------

Phase 4 carried an explicit `0.10 * staleness` term. It is deliberately removed
here, not merely reweighted: `weakness` is now computed from EFFECTIVE mastery,
which already discounts a score by how long it has gone unpractised. Keeping both
would count elapsed time twice, and would make a topic's priority depend on the
decay curve in two places that could drift apart.

Its weight moved to `review_pressure`, which is genuinely new information — how many
flashcards for this topic are due — and 0.05 went to weakness, which now carries the
time signal as well as the score.

SPACED REVIEW
-------------

Priority alone would rarely revisit a topic once it is Strong, so the student's best
topics would silently rot. When a quiz covers `SPACED_REVIEW_MIN_TOPICS` or more
topics AND no Strong topic won a slot on merit, the last slot is given to the
stalest Strong topic instead.

The "on merit" check matters: staleness already feeds the priority score, so a
long-unpractised strong topic is often selected anyway. Substituting in that case
would drop a topic that earned its place in favour of an arbitrary other one.

DIFFICULTY
==========

Difficulty is a *mix*, not a switch. Each topic's mastery selects a target
distribution:

    band            easy  medium  hard
    not started      50%    50%     0%
    needs practice   60%    40%     0%
    developing       25%    50%    25%
    strong           10%    40%    50%

Counts are allocated by the largest-remainder method, which is deterministic and
distributes rounding fairly. Two consequences are deliberate: a weak student always
gets 40% medium questions rather than easy ones forever, and a strong student always
gets 40% medium review rather than only hard ones.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.models import Difficulty
from app.services.learning.mastery import (
    DEVELOPING,
    MIN_EVIDENCE,
    NEEDS_PRACTICE,
    NOT_STARTED,
    STRONG,
    MasteryState,
    band_for,
)

# Weights for the priority score. They sum to 1.0 so priority stays in [0, 1].
W_WEAKNESS = 0.50
W_EVIDENCE = 0.25
W_RECENT_MISS = 0.15
W_REVIEW_PRESSURE = 0.10

# Due cards on one topic at which review pressure is considered maximal.
REVIEW_PRESSURE_FULL = 5.0

# Below this many topics in a quiz, every slot goes to the highest-priority topics;
# reserving one for review would crowd out the material that actually needs work.
SPACED_REVIEW_MIN_TOPICS = 3

DIFFICULTY_MIX: dict[str, dict[Difficulty, float]] = {
    NOT_STARTED: {Difficulty.EASY: 0.50, Difficulty.MEDIUM: 0.50, Difficulty.HARD: 0.0},
    NEEDS_PRACTICE: {
        Difficulty.EASY: 0.60,
        Difficulty.MEDIUM: 0.40,
        Difficulty.HARD: 0.0,
    },
    DEVELOPING: {Difficulty.EASY: 0.25, Difficulty.MEDIUM: 0.50, Difficulty.HARD: 0.25},
    STRONG: {Difficulty.EASY: 0.10, Difficulty.MEDIUM: 0.40, Difficulty.HARD: 0.50},
}


@dataclass(frozen=True)
class TopicCandidate:
    """A topic plus the student's mastery of it, as the selector sees it.

    `effective_mastery` is supplied by the caller rather than computed here so the
    selector stays a pure function of its inputs and can be tested at any point on
    the timeline without a clock.
    """

    topic_id: uuid.UUID
    name: str
    state: MasteryState
    effective_mastery: float = 0.0
    # Flashcards for this topic that are due or overdue.
    due_cards: int = 0

    @property
    def band(self) -> str:
        return band_for(self.state)

    @property
    def effective_band(self) -> str:
        """Band by present estimate rather than by demonstrated peak.

        A topic can be stored-Strong and effective-Developing at once; the adaptive
        engine cares about the latter.
        """
        if not self.state.has_evidence:
            return NOT_STARTED
        if self.effective_mastery < 40.0:
            return NEEDS_PRACTICE
        if self.effective_mastery < 70.0:
            return DEVELOPING
        return STRONG


@dataclass(frozen=True)
class SelectedTopic:
    topic_id: uuid.UUID
    name: str
    question_count: int
    priority: float
    band: str
    # True when this slot was reserved for spaced review rather than won on priority.
    is_review: bool


def priority_for(candidate: TopicCandidate, *, now: datetime | None = None) -> float:
    """Score a topic's need for practice, in [0, 1]. Deterministic.

    `now` is accepted for signature stability but is no longer read: elapsed time
    reaches this function through `candidate.effective_mastery`.
    """
    state = candidate.state

    weakness = (100.0 - candidate.effective_mastery) / 100.0
    evidence_need = 1.0 - min(1.0, state.evidence / MIN_EVIDENCE)
    recent_miss = 1.0 if state.last_answer_correct is False else 0.0
    review_pressure = min(1.0, candidate.due_cards / REVIEW_PRESSURE_FULL)

    return (
        W_WEAKNESS * weakness
        + W_EVIDENCE * evidence_need
        + W_RECENT_MISS * recent_miss
        + W_REVIEW_PRESSURE * review_pressure
    )


def select_topics(
    candidates: list[TopicCandidate],
    *,
    question_count: int,
    max_topics: int = 4,
    now: datetime | None = None,
) -> list[SelectedTopic]:
    """Choose which topics an adaptive quiz should cover, and how many questions each.

    Ties break on topic name so the result is stable across runs and databases.
    """
    if not candidates or question_count <= 0:
        return []

    scored = sorted(
        ((priority_for(candidate, now=now), candidate) for candidate in candidates),
        key=lambda pair: (-pair[0], pair[1].name.lower()),
    )

    slots = min(max_topics, len(scored), question_count)
    chosen: list[tuple[float, TopicCandidate, bool]] = [
        (priority, candidate, False) for priority, candidate in scored[:slots]
    ]

    # Reserve the final slot for spaced review of a Strong topic — but only when no
    # Strong topic already made the cut on merit. A stale strong topic often scores
    # highly enough to be selected anyway; swapping it for a different one would be
    # pure churn, and would drop a topic that had earned its place.
    if slots >= SPACED_REVIEW_MIN_TOPICS and not any(
        candidate.effective_band == STRONG for _, candidate, _ in chosen
    ):
        already = {candidate.topic_id for _, candidate, _ in chosen}
        review = _stalest_strong(
            [candidate for _, candidate in scored if candidate.topic_id not in already],
            now=now,
        )
        if review is not None:
            chosen[-1] = (priority_for(review, now=now), review, True)

    counts = allocate_questions(question_count, len(chosen))

    return [
        SelectedTopic(
            topic_id=candidate.topic_id,
            name=candidate.name,
            question_count=count,
            priority=round(priority, 4),
            band=candidate.effective_band,
            is_review=is_review,
        )
        for (priority, candidate, is_review), count in zip(chosen, counts, strict=True)
        if count > 0
    ]


def difficulty_plan(band: str, question_count: int) -> dict[Difficulty, int]:
    """Allocate a topic's questions across difficulties by largest remainder."""
    mix = DIFFICULTY_MIX.get(band, DIFFICULTY_MIX[NOT_STARTED])
    if question_count <= 0:
        return {}

    exact = {level: mix[level] * question_count for level in Difficulty}
    counts = {level: int(exact[level]) for level in Difficulty}

    remaining = question_count - sum(counts.values())
    if remaining:
        # Largest fractional remainder wins; ties break on a fixed difficulty order
        # so the allocation is reproducible.
        order = sorted(
            Difficulty,
            key=lambda level: (
                -(exact[level] - counts[level]),
                list(Difficulty).index(level),
            ),
        )
        for level in order[:remaining]:
            counts[level] += 1

    return {level: count for level, count in counts.items() if count > 0}


def _stalest_strong(
    candidates: list[TopicCandidate], *, now: datetime | None
) -> TopicCandidate | None:
    strong = [candidate for candidate in candidates if candidate.effective_band == STRONG]
    if not strong:
        return None
    return max(strong, key=lambda c: (priority_for(c, now=now), c.name.lower()))


def allocate_questions(total: int, buckets: int) -> list[int]:
    """Spread `total` questions across `buckets` topics as evenly as possible.

    Earlier buckets (higher priority) receive the remainder.
    """
    if buckets <= 0:
        return []
    base, extra = divmod(total, buckets)
    return [base + (1 if index < extra else 0) for index in range(buckets)]
