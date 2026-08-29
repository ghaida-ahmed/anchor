"""Request and response contracts for the adaptive learning engine.

The most important thing in this file is the split between `QuizQuestionRead` and
`QuizQuestionResult`. The first is what the student receives while taking a quiz and
deliberately omits `correct_index`, `explanation` and the source; the second is
returned only after an answer is submitted. Answers cannot leak early because the
shape that would carry them is never used on the taking path.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models import (
    OPTIONS_PER_QUESTION,
    AnswerVerdict,
    Difficulty,
    GradingState,
    QuestionType,
    QuizMode,
)
from app.schemas.common import ORMModel
from app.services.learning.quiz_service import QuizFormat

MAX_QUIZ_QUESTIONS = 20
MIN_QUIZ_QUESTIONS = 3

# Mirrors MAX_ANSWER_CHARS in services/learning/grading.py. Rejected here with a
# clear message rather than silently truncated at the grader.
MAX_RESPONSE_CHARS = 2_000


# --- Topics --------------------------------------------------------------------


class TopicRead(ORMModel):
    id: uuid.UUID
    course_id: uuid.UUID
    name: str
    description: str
    is_active: bool
    created_at: datetime


class TopicExtractionResponse(BaseModel):
    """What changed, so the UI can explain a regeneration rather than just refresh."""

    created: list[TopicRead]
    reactivated: list[TopicRead]
    deactivated: list[TopicRead]
    unchanged: list[TopicRead]


# --- Provenance ----------------------------------------------------------------


class SourceRef(BaseModel):
    """Where a generated item came from, read from the stored chunk's own row."""

    document_id: uuid.UUID
    document_name: str
    # None for formats without real pages (TXT, Markdown) — never a fabricated 1.
    page_number: int | None
    chunk_id: uuid.UUID


# --- Quizzes -------------------------------------------------------------------


class QuizGenerateRequest(BaseModel):
    mode: QuizMode = QuizMode.ADAPTIVE
    question_count: int = Field(default=8, ge=MIN_QUIZ_QUESTIONS, le=MAX_QUIZ_QUESTIONS)
    # Standard mode only. Ignored for adaptive, where the engine chooses.
    topic_ids: list[uuid.UUID] = Field(default_factory=list)
    difficulty: Difficulty | None = None
    # Defaults to multiple choice, so a client written before short answers
    # existed keeps getting exactly the quiz it used to get.
    quiz_format: QuizFormat = QuizFormat.MCQ

    @field_validator("topic_ids")
    @classmethod
    def _cap_topics(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(value) > 10:
            raise ValueError("Select at most 10 topics.")
        return value


class QuizQuestionRead(ORMModel):
    """The taking view. No correct answer, no explanation, no source.

    For a short-answer question that also means no `reference_answer`, no
    `key_concepts` and no `rubric`: those are the short-answer equivalent of
    `correct_index`, and shipping them to the client before submission would hand
    the student the mark scheme. The taking path never uses a shape that carries
    them.
    """

    id: uuid.UUID
    position: int
    question_text: str
    question_type: QuestionType
    # Null for short answers — there is nothing to choose from.
    options: list[str] | None
    difficulty: Difficulty
    topic_id: uuid.UUID
    topic_name: str


class QuizRead(ORMModel):
    id: uuid.UUID
    course_id: uuid.UUID
    title: str
    mode: QuizMode
    selection_rationale: str
    difficulty_plan: dict[str, int]
    question_count: int
    created_at: datetime


class QuizDetail(QuizRead):
    questions: list[QuizQuestionRead]


# --- Attempts ------------------------------------------------------------------


class AnswerSubmit(BaseModel):
    question_id: uuid.UUID
    selected_index: int = Field(ge=0, le=OPTIONS_PER_QUESTION - 1)
    answered_in_seconds: int | None = Field(default=None, ge=0, le=86_400)


class ShortAnswerSubmit(BaseModel):
    """A written answer. Separate from `AnswerSubmit` so neither contract has an
    optional field that is really required for one of the two question types."""

    question_id: uuid.UUID
    response_text: str = Field(min_length=1, max_length=MAX_RESPONSE_CHARS)
    answered_in_seconds: int | None = Field(default=None, ge=0, le=86_400)

    @field_validator("response_text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Write an answer before submitting it.")
        return value


class ConceptResultRead(BaseModel):
    """One rubric line, and whether the answer satisfied it."""

    concept: str
    satisfied: bool


class AnswerResult(BaseModel):
    """Returned immediately after answering — this is where the answer is revealed.

    One shape covers both question types, with the other type's fields null. A
    multiple-choice result carries `selected_index` and `correct_index`; a written
    one carries the verdict, the rubric breakdown and the feedback.
    """

    question_id: uuid.UUID
    question_type: QuestionType
    explanation: str
    source: SourceRef | None

    # Multiple choice.
    selected_index: int | None = None
    correct_index: int | None = None

    # Null for an `uncertain` verdict and for a grading failure: neither is a
    # boolean outcome, and coercing one would report a judgement nobody made.
    is_correct: bool | None = None

    # Short answer.
    response_text: str | None = None
    verdict: AnswerVerdict | None = None
    grading_state: GradingState = GradingState.NOT_REQUIRED
    rubric_results: list[ConceptResultRead] = Field(default_factory=list)
    feedback: str | None = None
    # Shown only after the answer is submitted, exactly like `correct_index`.
    reference_answer: str | None = None
    # True when the answer was recorded but could not be marked, so the UI can say
    # so instead of showing a silent blank.
    grading_failed: bool = False


class AttemptRead(ORMModel):
    id: uuid.UUID
    quiz_id: uuid.UUID
    started_at: datetime
    completed_at: datetime | None
    score_percent: float | None
    correct_count: int


class AttemptSummary(AttemptRead):
    """The completed-attempt view, with per-question results."""

    quiz_title: str
    question_count: int
    results: list[AnswerResult]


# --- Mastery -------------------------------------------------------------------


class TopicMasteryRead(BaseModel):
    topic_id: uuid.UUID
    topic_name: str
    mastery_score: float
    band: str
    band_label: str
    questions_attempted: int
    correct_answers: int
    # None when nothing has been attempted — not zero, which would read as failure.
    accuracy: float | None
    last_practised_at: datetime | None


class CourseMasteryRead(BaseModel):
    course_id: uuid.UUID
    topics: list[TopicMasteryRead]
    # Averaged over attempted topics only; None when nothing has been attempted.
    overall_mastery: float | None
    topics_total: int
    topics_started: int
    topics_strong: int
    questions_answered: int
    correct_answers: int
    accuracy: float | None
    strongest_topic: str | None
    weakest_topic: str | None


class RecommendationRead(BaseModel):
    kind: str
    title: str
    detail: str
    topic_id: uuid.UUID | None
    topic_name: str | None


# --- Flashcards ----------------------------------------------------------------


class FlashcardGenerateRequest(BaseModel):
    topic_ids: list[uuid.UUID] = Field(default_factory=list)
    # When true, ANCHOR picks the topics using the same deterministic priority the
    # adaptive quiz uses.
    weak_topics_only: bool = False


class FlashcardRead(ORMModel):
    id: uuid.UUID
    course_id: uuid.UUID
    topic_id: uuid.UUID
    topic_name: str
    front: str
    back: str
    source: SourceRef | None
    created_at: datetime
