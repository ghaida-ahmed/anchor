import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.quiz import Quiz, QuizQuestion
    from app.models.user import User


class QuizAttempt(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One student's run through one quiz.

    A quiz can be attempted more than once; each attempt is scored independently,
    and each answer updates mastery when it is recorded.
    """

    __tablename__ = "quiz_attempts"
    __table_args__ = (
        CheckConstraint(
            "score_percent IS NULL OR (score_percent >= 0 AND score_percent <= 100)",
            name="score_percent_range",
        ),
    )

    quiz_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("quizzes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Null until the student completes it; an abandoned attempt stays open and does
    # not pollute the score history.
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True
    )
    score_percent: Mapped[float | None] = mapped_column(
        Float, default=None, nullable=True
    )
    correct_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    quiz: Mapped["Quiz"] = relationship(back_populates="attempts")
    user: Mapped["User"] = relationship(back_populates="quiz_attempts")
    answers: Mapped[list["QuizAnswer"]] = relationship(
        back_populates="attempt", cascade="all, delete-orphan"
    )

    @property
    def is_complete(self) -> bool:
        return self.completed_at is not None

    def __repr__(self) -> str:
        state = f"{self.score_percent:.0f}%" if self.is_complete else "in progress"
        return f"<QuizAttempt {state}>"


class AnswerVerdict(str, enum.Enum):
    """The outcome of grading one answer.

    `UNCERTAIN` is a first-class result, not an error code. Rubric-based assessment
    is fallible, and an answer the grader could not confidently judge must neither
    reward nor penalise the student — so it contributes no mastery evidence and is
    excluded from the score denominator.
    """

    CORRECT = "correct"
    PARTIALLY_CORRECT = "partially_correct"
    INCORRECT = "incorrect"
    UNCERTAIN = "uncertain"


class GradingState(str, enum.Enum):
    """Whether grading has happened.

    `FAILED` means the provider could not be reached or returned something
    unusable. The response is preserved and the answer can be re-graded; it is
    never silently marked incorrect.
    """

    NOT_REQUIRED = "not_required"
    GRADED = "graded"
    FAILED = "failed"


class QuizAnswer(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One answer within an attempt.

    `is_correct` is stored rather than derived so a later edit to a question — or a
    deleted question — cannot silently rewrite history.
    """

    __tablename__ = "quiz_answers"
    __table_args__ = (
        # One answer per question per attempt; re-answering updates the row.
        UniqueConstraint("attempt_id", "question_id", name="uq_quiz_answers_attempt_q"),
    )

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("quiz_attempts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("quiz_questions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # MCQ only. Null for short answers.
    selected_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Null when the verdict is `uncertain` — the answer was neither right nor wrong
    # as far as ANCHOR can tell, and forcing a boolean would lose that.
    is_correct: Mapped[bool | None] = mapped_column(nullable=True)
    # Seconds spent on the question, when the client reports it.
    answered_in_seconds: Mapped[int | None] = mapped_column(
        Integer, default=None, nullable=True
    )

    # --- Short answer -------------------------------------------------------
    # The student's response, preserved verbatim even when grading fails.
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    verdict: Mapped[AnswerVerdict | None] = mapped_column(
        Enum(AnswerVerdict, name="answer_verdict", native_enum=False), nullable=True
    )
    # Per-concept results as [{concept, satisfied}], for showing what was missed.
    rubric_results: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    grading_state: Mapped[GradingState] = mapped_column(
        Enum(GradingState, name="grading_state", native_enum=False),
        default=GradingState.NOT_REQUIRED,
        server_default=GradingState.NOT_REQUIRED.name,
        nullable=False,
    )
    graded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True
    )
    # Which model produced the verdict, for auditing a disputed grade later.
    # Deliberately no prompt, no chain-of-thought and no copied excerpts.
    grader_model: Mapped[str | None] = mapped_column(String(120), nullable=True)

    attempt: Mapped["QuizAttempt"] = relationship(back_populates="answers")
    question: Mapped["QuizQuestion"] = relationship()

    def __repr__(self) -> str:
        outcome = self.verdict.value if self.verdict else "ungraded"
        return f"<QuizAnswer {outcome}>"
