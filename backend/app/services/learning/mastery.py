"""The mastery algorithm.

Pure functions over plain values — no database, no network, and emphatically no
language model. Adaptation must be explainable and reproducible, and an LLM is
neither.

THE FORMULA
===========

On every answered question, for that topic:

    raw' = raw + (ALPHA * w) * (target - raw)

    target = 100 if the answer was correct else 0
    ALPHA  = 0.30                     (base learning rate)
    w      = EVIDENCE_WEIGHT[difficulty][correct]

This is an exponentially-weighted moving average, so each new answer pulls the
score a fraction of the way towards the outcome. Older answers keep decaying in
influence without ever needing to be stored or re-read — which is exactly the
"recent answers matter more" requirement, and it costs one float.

WHY THE WEIGHT DEPENDS ON DIFFICULTY *AND* OUTCOME
--------------------------------------------------

Not all answers are equally informative. Getting an easy question right is what
anyone would expect and says little; getting an easy question wrong is a strong
signal of a gap. Hard questions are the mirror image.

                correct   incorrect
    easy          0.6        1.2
    medium        1.0        1.0
    hard          1.4        0.7

So the step size tracks how *surprising* the outcome was, not merely whether it was
right. This is what stops a strong student being wrecked by one hard miss (step
0.30*0.7 = 0.21) while still punishing an easy miss properly (0.30*1.2 = 0.36).

CONFIDENCE DAMPING
------------------

`raw` alone would let a single correct answer read as substantial mastery. The
displayed score is therefore damped by how much evidence exists:

    confidence = min(1, questions_attempted / MIN_EVIDENCE)     MIN_EVIDENCE = 5
    mastery    = raw * (0.5 + 0.5 * confidence)

With one answer the student sees at most half of `raw`; by the fifth the damping is
gone. The two values are stored separately so the update rule stays a pure function
of the previous state.

WORKED EXAMPLES
---------------

    one lucky easy-correct from zero : raw 18.0 -> mastery 10.8   (not mastery)
    one hard-correct from zero       : raw 42.0 -> mastery 25.2   (not Strong)
    80 raw, then one hard-miss       : raw 63.2                   (dented, not lost)
    80 raw, then one easy-miss       : raw 51.2                   (bigger dent)
"""

from dataclasses import dataclass, replace
from datetime import datetime

from app.core.clock import now
from app.models import Difficulty

# Base learning rate: the fraction of the gap closed by a perfectly average answer.
ALPHA = 0.30

# How informative an outcome is, by difficulty and correctness. See module docstring.
EVIDENCE_WEIGHT: dict[Difficulty, dict[bool, float]] = {
    Difficulty.EASY: {True: 0.6, False: 1.2},
    Difficulty.MEDIUM: {True: 1.0, False: 1.0},
    Difficulty.HARD: {True: 1.4, False: 0.7},
}

# Answers needed before the displayed score stops being damped.
MIN_EVIDENCE = 5

# --- Bands ---------------------------------------------------------------------
# Chosen so they line up with the difficulty mix in `adaptive.py`: a student is
# moved up a band roughly when they can handle the next difficulty tier.
NEEDS_PRACTICE_BELOW = 40.0
STRONG_AT_OR_ABOVE = 70.0


# A flashcard review is self-reported recall, so it counts for less than answering
# a multiple-choice question. Used for confidence damping and for decay's evidence
# term; the mastery update itself weights flashcards separately (see
# FLASHCARD_EVIDENCE_WEIGHT).
FLASHCARD_EVIDENCE_VALUE = 0.4


@dataclass(frozen=True)
class MasteryState:
    """The stored state the update rule reads and writes."""

    raw_score: float
    mastery_score: float
    questions_attempted: int
    correct_answers: int
    last_answer_correct: bool | None = None
    last_practised_at: datetime | None = None
    # Flashcard reviews are tracked apart from quiz questions: the UI labels
    # `questions_attempted` "questions answered", and self-reported recall should
    # not silently inflate that number.
    flashcard_reviews: int = 0

    @property
    def evidence(self) -> float:
        """Total evidence behind the score, in quiz-question equivalents."""
        flashcard_value = FLASHCARD_EVIDENCE_VALUE * self.flashcard_reviews
        return self.questions_attempted + flashcard_value

    @property
    def has_evidence(self) -> bool:
        return self.questions_attempted > 0 or self.flashcard_reviews > 0


NEW_TOPIC = MasteryState(
    raw_score=0.0,
    mastery_score=0.0,
    questions_attempted=0,
    correct_answers=0,
)


def displayed_mastery(raw_score: float, evidence: float) -> float:
    """Damp the raw estimate by how much evidence supports it.

    `evidence` is in quiz-question equivalents, so flashcard reviews contribute
    but at reduced value.
    """
    confidence = min(1.0, max(0.0, evidence) / MIN_EVIDENCE)
    return _clamp(raw_score * (0.5 + 0.5 * confidence))


def apply_answer(
    state: MasteryState,
    *,
    difficulty: Difficulty,
    correct: bool,
    answered_at: datetime | None = None,
) -> MasteryState:
    """Fold one answer into a topic's mastery. Pure, deterministic, total."""
    weight = EVIDENCE_WEIGHT[difficulty][correct]
    target = 100.0 if correct else 0.0

    # Step is capped below 1.0 so the score can never overshoot the target.
    step = min(ALPHA * weight, 0.9)
    raw = _clamp(state.raw_score + step * (target - state.raw_score))

    attempted = state.questions_attempted + 1
    correct_count = state.correct_answers + (1 if correct else 0)

    updated = MasteryState(
        raw_score=raw,
        mastery_score=0.0,
        questions_attempted=attempted,
        correct_answers=correct_count,
        last_answer_correct=correct,
        last_practised_at=answered_at or now(),
        flashcard_reviews=state.flashcard_reviews,
    )
    return replace(updated, mastery_score=displayed_mastery(raw, updated.evidence))


# --- Flashcard evidence --------------------------------------------------------
#
# Quiz answers stay the strongest evidence. A flashcard rating is the student's own
# judgement of whether they recalled something, which is useful but softer, so it
# moves the score by roughly a third as much as a medium quiz question.
#
# `None` means the rating carries no mastery signal at all.

FLASHCARD_EVIDENCE_WEIGHT: dict[str, tuple[bool, float] | None] = {
    "again": (False, 0.50),  # negative evidence, softer than a quiz miss
    "hard": None,  # recalled, but with effort — too ambiguous to score
    "good": (True, 0.35),
    "easy": (True, 0.45),
}

# Ceiling on what flashcard evidence alone can demonstrate. Repeatedly pressing
# Easy is not proof of mastery, so positive flashcard evidence stops lifting the
# score here; only quiz answers can push it higher. Negative evidence is never
# capped — failing a card should always be able to lower a score.
FLASHCARD_RAW_CEILING = 75.0


def apply_flashcard_review(
    state: MasteryState,
    *,
    rating: str,
    reviewed_at: datetime | None = None,
) -> MasteryState:
    """Fold one flashcard rating into a topic's mastery.

    Returns the state unchanged (apart from the review counter and timestamp) for
    ratings that carry no signal, and never lets positive evidence push the raw
    score past `FLASHCARD_RAW_CEILING`.
    """
    signal = FLASHCARD_EVIDENCE_WEIGHT.get(rating)
    reviews = state.flashcard_reviews + 1
    moment = reviewed_at or now()

    if signal is None:
        updated = replace(state, flashcard_reviews=reviews, last_practised_at=moment)
        return replace(
            updated, mastery_score=displayed_mastery(updated.raw_score, updated.evidence)
        )

    correct, weight = signal
    target = 100.0 if correct else 0.0
    step = min(ALPHA * weight, 0.9)
    raw = _clamp(state.raw_score + step * (target - state.raw_score))

    if correct and raw > FLASHCARD_RAW_CEILING:
        # Do not let self-reported recall carry the score above the ceiling, but do
        # not claw back a higher score that quizzes already earned.
        raw = max(state.raw_score, FLASHCARD_RAW_CEILING)

    updated = MasteryState(
        raw_score=raw,
        mastery_score=0.0,
        questions_attempted=state.questions_attempted,
        correct_answers=state.correct_answers,
        last_answer_correct=state.last_answer_correct,
        last_practised_at=moment,
        flashcard_reviews=reviews,
    )
    return replace(updated, mastery_score=displayed_mastery(raw, updated.evidence))


class MasteryBand(str):
    """String enum-ish band label. Plain strings keep it trivial to serialise."""


NOT_STARTED = "not_started"
NEEDS_PRACTICE = "needs_practice"
DEVELOPING = "developing"
STRONG = "strong"

BAND_LABELS = {
    NOT_STARTED: "Not started",
    NEEDS_PRACTICE: "Needs practice",
    DEVELOPING: "Developing",
    STRONG: "Strong",
}


def band_for(state: MasteryState) -> str:
    """Classify a topic.

    "Not started" is a distinct band, not a synonym for zero: a student who has
    never seen a topic has not failed it, and the UI must not imply otherwise.
    """
    if not state.has_evidence:
        return NOT_STARTED
    if state.mastery_score < NEEDS_PRACTICE_BELOW:
        return NEEDS_PRACTICE
    if state.mastery_score < STRONG_AT_OR_ABOVE:
        return DEVELOPING
    return STRONG


def accuracy(state: MasteryState) -> float | None:
    """Lifetime percentage correct. Reported alongside mastery, never as mastery."""
    if state.questions_attempted == 0:
        return None
    return 100.0 * state.correct_answers / state.questions_attempted


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


# --- Short answers -------------------------------------------------------------
#
# A short answer is stronger evidence than a multiple-choice answer: there are no
# options to eliminate and nothing to guess, so producing the right content really
# does demonstrate recall. The weights below are therefore larger than
# EVIDENCE_WEIGHT for correct answers, and the easy/hard asymmetry is the same
# shape for the same reason — an easy short answer missed is a bad sign, a hard one
# missed much less so.
#
#                    correct   incorrect
#     easy             0.8        1.3
#     medium           1.3        1.1
#     hard             1.7        0.8
#
# `partially_correct` is the one case where the target is not 0 or 100. A partial
# answer is genuine partial knowledge, so it pulls the score towards 60 — above
# NEEDS_PRACTICE_BELOW, below STRONG_AT_OR_ABOVE — with a small weight, because a
# rubric-based partial judgement is the least certain thing this grader produces.
# Note this can pull a strong score DOWN, which is intended: a student sitting at
# 85 who can only half-answer has overestimated the topic.
#
# `uncertain` appears in neither table. It is handled before this point: an answer
# the grader could not judge produces no mastery change and no evidence at all.
#
# Worked example, one correct medium short answer from zero:
#     step = 0.30 * 1.3 = 0.39   ->  raw = 39.0
#     evidence 1 -> confidence 0.2 -> displayed = 39.0 * 0.6 = 23.4
# Against 18.0 for the equivalent MCQ. Still nowhere near Strong on one answer,
# which is the confidence damping doing its job.

SHORT_ANSWER_PARTIAL_TARGET = 60.0
SHORT_ANSWER_PARTIAL_WEIGHT = 0.6

SHORT_ANSWER_WEIGHT: dict[Difficulty, dict[bool, float]] = {
    Difficulty.EASY: {True: 0.8, False: 1.3},
    Difficulty.MEDIUM: {True: 1.3, False: 1.1},
    Difficulty.HARD: {True: 1.7, False: 0.8},
}


def short_answer_signal(
    verdict: str, difficulty: Difficulty
) -> tuple[float, float] | None:
    """The `(target, weight)` a verdict contributes, or None for no signal.

    Kept separate from `apply_short_answer` so the policy can be read, tested and
    quoted in the UI without running an update.
    """
    if verdict == "correct":
        return 100.0, SHORT_ANSWER_WEIGHT[difficulty][True]
    if verdict == "incorrect":
        return 0.0, SHORT_ANSWER_WEIGHT[difficulty][False]
    if verdict == "partially_correct":
        return SHORT_ANSWER_PARTIAL_TARGET, SHORT_ANSWER_PARTIAL_WEIGHT
    # "uncertain", or anything unrecognised: no signal, and deliberately not an
    # error — refusing to score is the safe outcome here.
    return None


def apply_short_answer(
    state: MasteryState,
    *,
    difficulty: Difficulty,
    verdict: str,
    answered_at: datetime | None = None,
) -> MasteryState:
    """Fold one graded short answer into a topic's mastery.

    An `uncertain` verdict returns the state completely untouched — not even the
    attempt counter moves. Counting it as evidence would dilute the confidence
    damping on the strength of an answer nobody could judge, and counting it as
    practice would refresh the retention clock for a topic the student may not
    actually recall.
    """
    signal = short_answer_signal(verdict, difficulty)
    if signal is None:
        return state

    target, weight = signal
    step = min(ALPHA * weight, 0.9)
    raw = _clamp(state.raw_score + step * (target - state.raw_score))

    attempted = state.questions_attempted + 1
    # Partial credit is not a correct answer. The accuracy figure shown next to
    # mastery counts whole correct answers only, so half-credit would inflate it.
    correct_count = state.correct_answers + (1 if verdict == "correct" else 0)

    updated = MasteryState(
        raw_score=raw,
        mastery_score=0.0,
        questions_attempted=attempted,
        correct_answers=correct_count,
        last_answer_correct=(verdict == "correct"),
        last_practised_at=answered_at or now(),
        flashcard_reviews=state.flashcard_reviews,
    )
    return replace(updated, mastery_score=displayed_mastery(raw, updated.evidence))
