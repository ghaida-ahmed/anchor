"""Layer 2 of short-answer grading: the one model call, and what surrounds it.

The layers, in order:

    1. `grading.sanitise_student_answer` / `trivially_incorrect` — deterministic
       guards. Forged fence markers and control characters are neutralised, an
       empty answer is marked without spending a call.
    2. this module — one structured call, with the student's text fenced and
       explicitly labelled as data.
    3. `grading.validate_grade` — the model's answer is checked against the
       question's OWN key concepts and rejected if it contradicts itself.

What is stored is the verdict, the per-concept results, the feedback shown to the
student, and the model name. Not the prompt, not the excerpts, and not any
reasoning the model may have produced along the way: a stored chain of thought is
unverifiable text that reads like a justification, and keeping it would invite
treating it as one.
"""

from dataclasses import dataclass

from app.core.clock import now
from app.core.config import settings
from app.models import AnswerVerdict, GradingState, QuizQuestion
from app.services.learning import grading
from app.services.learning.prompts import (
    GRADING_SCHEMA,
    GRADING_SYSTEM,
    grading_prompt,
)
from app.services.rag.generation import ChatMessage, GenerationError, LLMProvider

# Feedback for an answer with no content. Written here, not by the model.
EMPTY_ANSWER_FEEDBACK = (
    "This was left blank or too short to mark. Have another go — even a partial "
    "answer in your own words is worth writing down."
)


@dataclass(frozen=True)
class GradingResult:
    """Everything the caller writes to the answer row."""

    state: GradingState
    outcome: grading.GradeOutcome | None
    # Recorded only when a model was actually consulted.
    grader_model: str | None = None

    @property
    def verdict(self) -> AnswerVerdict | None:
        return self.outcome.verdict if self.outcome else None

    @property
    def affects_mastery(self) -> bool:
        """Whether this result should move the student's mastery at all.

        False for `uncertain` and for any failure. Both mean the same thing to the
        student's record: nothing happened.
        """
        return (
            self.state is GradingState.GRADED
            and self.outcome is not None
            and self.outcome.verdict is not AnswerVerdict.UNCERTAIN
        )


class GradingService:
    def __init__(self, llm: LLMProvider) -> None:
        self.llm = llm

    def grade(self, question: QuizQuestion, response_text: str) -> GradingResult:
        """Mark one short answer. Never raises for a bad answer or a bad provider."""
        concepts = _concepts_of(question)
        if not concepts:
            # A short-answer question is not persisted without concepts, so this
            # means the row predates or bypassed validation. Refuse to invent a
            # rubric rather than mark against nothing.
            return GradingResult(state=GradingState.FAILED, outcome=None)

        answer = grading.sanitise_student_answer(response_text)

        if grading.trivially_incorrect(answer):
            return GradingResult(
                state=GradingState.GRADED,
                outcome=grading.GradeOutcome(
                    verdict=AnswerVerdict.INCORRECT,
                    concept_results=[
                        grading.ConceptResult(concept=concept, satisfied=False)
                        for concept in concepts
                    ],
                    feedback=EMPTY_ANSWER_FEEDBACK,
                ),
            )

        answer, _truncated = grading.truncate_answer(answer)

        try:
            raw = self.llm.generate_json(
                [
                    ChatMessage(role="system", content=GRADING_SYSTEM),
                    ChatMessage(
                        role="user",
                        content=grading_prompt(
                            question.question_text,
                            question.reference_answer or "",
                            concepts,
                            question.rubric or "",
                            answer,
                        ),
                    ),
                ],
                GRADING_SCHEMA,
            )
        except GenerationError:
            # The student answered; the provider did not. That is not their
            # mistake, so the answer is kept and can be graded again later.
            return GradingResult(state=GradingState.FAILED, outcome=None)

        outcome = grading.validate_grade(raw, concepts)
        if outcome is None:
            return GradingResult(state=GradingState.FAILED, outcome=None)

        return GradingResult(
            state=GradingState.GRADED,
            outcome=outcome,
            grader_model=settings.llm_model,
        )

    @staticmethod
    def graded_at():
        return now()


def _concepts_of(question: QuizQuestion) -> list[str]:
    raw = question.key_concepts
    if not isinstance(raw, list):
        return []
    return [
        concept.strip() for concept in raw if isinstance(concept, str) and concept.strip()
    ]
