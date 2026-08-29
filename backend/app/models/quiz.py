import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.course import Course
    from app.models.document import Document
    from app.models.document_chunk import DocumentChunk
    from app.models.quiz_attempt import QuizAttempt
    from app.models.topic import Topic
    from app.models.user import User

# A question always has exactly this many options. Enforced in validation, not just
# by convention — a 3- or 5-option question would break the UI and the scoring.
OPTIONS_PER_QUESTION = 4


class QuestionType(str, enum.Enum):
    """How a question is answered and graded.

    MCQ is graded deterministically by comparing indices. SHORT_ANSWER needs a
    rubric-based assessment, which is the only place in ANCHOR where a model judges
    a student's work — and where an `uncertain` verdict exists precisely because
    that judgement is not infallible.
    """

    MCQ = "mcq"
    SHORT_ANSWER = "short_answer"


class Difficulty(str, enum.Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class QuizMode(str, enum.Enum):
    """How the quiz's topics were chosen.

    `STANDARD` means the student picked them. `ADAPTIVE` means ANCHOR's mastery
    algorithm did — deterministically, in `services/learning/adaptive.py`. The model
    never chooses; it only writes questions for topics already selected.
    """

    STANDARD = "standard"
    ADAPTIVE = "adaptive"
    # Exam prep: coverage-first selection under a deadline, widening as it nears.
    EXAM = "exam"


class Quiz(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A generated set of questions, persisted so a page refresh costs nothing."""

    __tablename__ = "quizzes"
    __table_args__ = (
        Index("ix_quizzes_course_id_created_at", "course_id", "created_at"),
    )

    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    # Quizzes belong to the student who generated them: two students on the same
    # course get different adaptive quizzes.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    mode: Mapped[QuizMode] = mapped_column(
        Enum(QuizMode, name="quiz_mode", native_enum=False), nullable=False
    )
    # Why the adaptive engine chose these topics, in the student's language. Built
    # from templates by the backend — never an LLM call.
    selection_rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # The difficulty mix actually requested, e.g. {"easy": 2, "medium": 2, "hard": 1}.
    difficulty_plan: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    course: Mapped["Course"] = relationship(back_populates="quizzes")
    user: Mapped["User"] = relationship(back_populates="quizzes")
    questions: Mapped[list["QuizQuestion"]] = relationship(
        back_populates="quiz",
        cascade="all, delete-orphan",
        order_by="QuizQuestion.position",
    )
    attempts: Mapped[list["QuizAttempt"]] = relationship(
        back_populates="quiz", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Quiz {self.title} ({self.mode.value})>"


class QuizQuestion(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One question — multiple choice or short answer — with source provenance.

    The answer key (`correct_index`, `reference_answer`, `rubric`, `key_concepts`,
    `explanation`) is deliberately NOT part of the schema the quiz-taking endpoint
    returns. It is revealed only after the student submits.
    """

    __tablename__ = "quiz_questions"

    quiz_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("quizzes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), index=True, nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    question_type: Mapped[QuestionType] = mapped_column(
        Enum(QuestionType, name="question_type", native_enum=False),
        default=QuestionType.MCQ,
        server_default=QuestionType.MCQ.name,
        nullable=False,
    )
    question_text: Mapped[str] = mapped_column(Text, nullable=False)

    # --- Multiple choice ----------------------------------------------------
    # Nullable so short-answer questions do not carry empty arrays. Existing MCQ
    # rows are unaffected; validation enforces presence per question type.
    options: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    correct_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- Short answer -------------------------------------------------------
    # The grounded answer the rubric is judged against. Never sent to the client
    # before submission — see schemas/learning.py.
    reference_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Concepts a full answer should contain, as a list of strings. The grader
    # reports which were satisfied.
    key_concepts: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    rubric: Mapped[str | None] = mapped_column(Text, nullable=True)

    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[Difficulty] = mapped_column(
        Enum(Difficulty, name="difficulty", native_enum=False), nullable=False
    )

    # --- Provenance ---------------------------------------------------------
    # Foreign keys to the real records, not display strings: the document name and
    # page number are read from them at render time, so a renamed file stays correct
    # and a page number can never be fabricated.
    source_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="SET NULL"), nullable=True
    )
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )

    quiz: Mapped["Quiz"] = relationship(back_populates="questions")
    topic: Mapped["Topic"] = relationship()
    source_chunk: Mapped["DocumentChunk | None"] = relationship()
    source_document: Mapped["Document | None"] = relationship()

    def __repr__(self) -> str:
        return (
            f"<QuizQuestion {self.position} ({self.question_type.value}): "
            f"{self.question_text[:40]}…>"
        )
