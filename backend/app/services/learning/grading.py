"""Short-answer grading: the deterministic layers around the model.

Grading a free-text answer is the one place in ANCHOR where a language model makes
a judgement that directly changes a student's record. It is therefore wrapped on
both sides:

    Layer 1  deterministic guards on the student's input   (this module)
    Layer 2  structured assessment against a rubric        (grading_service.py)
    Layer 3  deterministic validation of what came back    (this module)

WHY NOT EMBEDDING SIMILARITY
============================

Cosine similarity between the student's answer and the reference answer is the
obvious cheap grader and it is wrong for this job. It scores topical overlap, not
correctness: "TCP halves the window on loss" and "TCP doubles the window on loss"
embed almost identically and mean opposite things, while a correct answer in
different vocabulary can score lower than a fluent wrong one. Similarity cannot
represent negation, and negation is most of what distinguishes right from wrong
here. It is not used as the grader, nor as a tie-breaker.

WHY `uncertain` EXISTS
======================

Rubric marking is fallible, so the grader is given a way to say so. An `uncertain`
verdict:

    * changes mastery not at all — no reward, no penalty, no evidence counted
    * is excluded from the attempt's score DENOMINATOR, not counted as a miss
    * is shown to the student as unmarked, with the answer preserved

Silently treating "I could not judge this" as "wrong" would be the worst available
option: it penalises the student for the grader's limitation and hides it.

SCORING
=======

    correct            1.0
    partially_correct  0.5
    incorrect          0.0
    uncertain          excluded

Half credit for a partial answer matches the mastery weighting, where
`partially_correct` pulls towards 60 rather than towards 100 or 0.
"""

import re
import unicodedata
from dataclasses import dataclass

from app.models import AnswerVerdict
from app.services.learning.prompts import (
    STUDENT_ANSWER_FENCE,
    STUDENT_ANSWER_FENCE_END,
)

# Shorter than this cannot address a short-answer question. Marked incorrect
# without a model call: it costs quota to be told what is already obvious.
MIN_ANSWER_CHARS = 2

# Longer than this is truncated before grading. A very long answer is usually a
# paste, and an unbounded response is also an unbounded prompt.
MAX_ANSWER_CHARS = 2_000

# Feedback longer than this is truncated on display; the model is asked for two or
# three sentences.
MAX_FEEDBACK_CHARS = 600

VERDICT_CREDIT: dict[AnswerVerdict, float | None] = {
    AnswerVerdict.CORRECT: 1.0,
    AnswerVerdict.PARTIALLY_CORRECT: 0.5,
    AnswerVerdict.INCORRECT: 0.0,
    # None means "not counted", which is different from 0.0.
    AnswerVerdict.UNCERTAIN: None,
}

UNCERTAIN_FEEDBACK = (
    "This answer could not be marked with confidence, so it has not affected your "
    "mastery either way. Compare it with the model answer yourself, and re-answer "
    "if you would like it marked again."
)

_EMPTY_FEEDBACK = "Marked against the key concepts for this question."

# A student who writes the fence markers into their own answer would otherwise be
# able to end the quoted block early and address the grader directly. Any line that
# looks like a fence is neutralised before the prompt is built.
_FENCE_LIKE = re.compile(
    r"^\s*-{3,}\s*(?:BEGIN|END)\s+STUDENT\s+ANSWER\s*-{3,}\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Control characters other than tab and newline: invisible, and a known vector for
# hiding text from a reviewer while the model still reads it.
_CONTROL = re.compile(r"[^\S\t\n]|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass(frozen=True)
class ConceptResult:
    concept: str
    satisfied: bool


@dataclass(frozen=True)
class GradeOutcome:
    """The result of grading one answer, after every deterministic check."""

    verdict: AnswerVerdict
    concept_results: list[ConceptResult]
    feedback: str
    # True when Layer 3 overrode the model's own verdict.
    adjusted: bool = False

    @property
    def credit(self) -> float | None:
        return VERDICT_CREDIT[self.verdict]

    @property
    def is_correct(self) -> bool | None:
        """For the `is_correct` column. None for partial and uncertain alike —
        neither is a boolean outcome, and forcing one would lose that."""
        if self.verdict is AnswerVerdict.CORRECT:
            return True
        if self.verdict is AnswerVerdict.INCORRECT:
            return False
        return None

    def as_rubric_rows(self) -> list[dict]:
        return [
            {"concept": result.concept, "satisfied": result.satisfied}
            for result in self.concept_results
        ]


# --- Layer 1: the student's input ----------------------------------------------


def sanitise_student_answer(text: str) -> str:
    """Make a student's response safe to place inside the grading prompt.

    This is a containment measure, not a content filter — nothing is rejected for
    what it says. It removes the two things that let text escape its quoted block:
    forged fence markers, and invisible control characters. The answer's actual
    words are never altered, so what the grader marks is what the student wrote.
    """
    # NFKC folds the lookalike dashes and full-width characters that would slip a
    # forged fence past a literal match.
    normalised = unicodedata.normalize("NFKC", text)
    normalised = normalised.replace("\r\n", "\n").replace("\r", "\n")
    normalised = _CONTROL.sub(
        lambda match: " " if match.group().isspace() else "", normalised
    )
    normalised = _FENCE_LIKE.sub("[removed]", normalised)
    # Belt and braces: catch the exact markers even when they sit mid-line.
    normalised = normalised.replace(STUDENT_ANSWER_FENCE, "[removed]")
    normalised = normalised.replace(STUDENT_ANSWER_FENCE_END, "[removed]")
    return normalised.strip()


def trivially_incorrect(answer: str) -> bool:
    """Whether an answer can be marked wrong without asking the model.

    Deliberately narrow. Only an answer with essentially no content qualifies —
    anything a person might have meant goes to the grader, because guessing on the
    student's behalf is exactly what this pipeline is built to avoid.
    """
    return len(answer.strip()) < MIN_ANSWER_CHARS


def truncate_answer(answer: str) -> tuple[str, bool]:
    if len(answer) <= MAX_ANSWER_CHARS:
        return answer, False
    return answer[:MAX_ANSWER_CHARS].rstrip(), True


# --- Layer 3: what came back ---------------------------------------------------


def _normalise_concept(concept: str) -> str:
    return re.sub(r"\s+", " ", concept).strip().casefold()


def validate_grade(raw: object, key_concepts: list[str]) -> GradeOutcome | None:
    """Turn a model response into a verdict, or None if it is unusable.

    Returning None means grading FAILED, which is recorded as such. It never
    degrades to "incorrect": the student answered, and a provider problem is not
    their mistake.

    Two things are enforced here that the schema cannot:

    * the concept list is OURS. The model's rows are matched back onto the concepts
      stored with the question; a concept it invented is discarded, and one it
      omitted counts as unsatisfied. So the rubric shown to the student is always
      the rubric the question was written with.
    * the verdict must not contradict the concept results. "Correct" with nothing
      satisfied, or "incorrect" with everything satisfied, is not a judgement we
      can pass on — it becomes `uncertain`.
    """
    if not isinstance(raw, dict) or not key_concepts:
        return None

    verdict_text = str(raw.get("verdict") or "").strip().lower()
    try:
        verdict = AnswerVerdict(verdict_text)
    except ValueError:
        return None

    reported: dict[str, bool] = {}
    rows = raw.get("concept_results")
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            concept = row.get("concept")
            satisfied = row.get("satisfied")
            if not isinstance(concept, str) or not isinstance(satisfied, bool):
                continue
            reported[_normalise_concept(concept)] = satisfied

    results = [
        ConceptResult(
            concept=concept,
            satisfied=reported.get(_normalise_concept(concept), False),
        )
        for concept in key_concepts
    ]

    satisfied_count = sum(1 for result in results if result.satisfied)
    adjusted = False

    if verdict is not AnswerVerdict.UNCERTAIN:
        contradiction = (verdict is AnswerVerdict.CORRECT and satisfied_count == 0) or (
            verdict is AnswerVerdict.INCORRECT and satisfied_count == len(results)
        )
        if contradiction:
            verdict = AnswerVerdict.UNCERTAIN
            adjusted = True

    feedback = _clean_feedback(raw.get("feedback"), verdict, adjusted)
    return GradeOutcome(
        verdict=verdict, concept_results=results, feedback=feedback, adjusted=adjusted
    )


def _clean_feedback(value: object, verdict: AnswerVerdict, adjusted: bool) -> str:
    """Trim the feedback, and refuse to pass on anything that echoes the prompt.

    A response that repeats the fence markers is either confused or is relaying
    text from inside the student's answer. Either way it is replaced rather than
    shown.
    """
    if verdict is AnswerVerdict.UNCERTAIN and adjusted:
        # The model's own words described a verdict we just overrode; they would
        # contradict what the student is being shown.
        return UNCERTAIN_FEEDBACK

    text = str(value or "").strip()
    if not text:
        return (
            UNCERTAIN_FEEDBACK if verdict is AnswerVerdict.UNCERTAIN else _EMPTY_FEEDBACK
        )
    if STUDENT_ANSWER_FENCE in text or STUDENT_ANSWER_FENCE_END in text:
        return _EMPTY_FEEDBACK
    if len(text) > MAX_FEEDBACK_CHARS:
        text = text[:MAX_FEEDBACK_CHARS].rstrip() + "…"
    return text


# --- Attempt scoring -----------------------------------------------------------


@dataclass(frozen=True)
class AttemptScore:
    credit: float
    counted: int
    excluded: int

    @property
    def percent(self) -> float:
        return 100.0 * self.credit / self.counted if self.counted else 0.0


def score_attempt(
    verdicts: list[AnswerVerdict | None], *, unanswered: int = 0
) -> AttemptScore:
    """Score one attempt over mixed question types.

    `None` is an MCQ's absent verdict and never appears here — callers map a
    multiple-choice answer to CORRECT or INCORRECT before calling. `unanswered`
    counts questions the student skipped, which DO count against them: not
    answering is not the same as not being markable.
    """
    credit = 0.0
    counted = unanswered
    excluded = 0

    for verdict in verdicts:
        if verdict is None:
            excluded += 1
            continue
        value = VERDICT_CREDIT[verdict]
        if value is None:
            excluded += 1
            continue
        credit += value
        counted += 1

    return AttemptScore(credit=credit, counted=counted, excluded=excluded)
