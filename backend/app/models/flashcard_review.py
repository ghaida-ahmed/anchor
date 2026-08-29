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
    Index,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, UpdatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.course import Course
    from app.models.flashcard import Flashcard
    from app.models.user import User


class ReviewRating(str, enum.Enum):
    """How well the student felt they recalled a card.

    Self-reported, and deliberately so: the student knows whether they remembered
    it. Asking a language model to judge recall would be both expensive and less
    accurate than the person who just tried.

    Lives here rather than in the scheduler because it is persisted, and the model
    layer must not import from services.
    """

    AGAIN = "again"
    HARD = "hard"
    GOOD = "good"
    EASY = "easy"


class FlashcardReviewState(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """One student's scheduling state for one card.

    Deliberately separate from `Flashcard`. Cards are content; schedules belong to
    the person reviewing them. Keeping the schedule on the card would break the
    moment two students share a course, and would conflate "what this card says"
    with "when this person should see it again".
    """

    __tablename__ = "flashcard_review_states"
    __table_args__ = (
        UniqueConstraint("user_id", "flashcard_id", name="uq_review_state_user_card"),
        # The due-queue query: this user's cards in this course, ordered by due date.
        Index("ix_review_states_due", "user_id", "course_id", "due_at"),
        CheckConstraint("interval_days >= 0", name="interval_non_negative"),
        CheckConstraint("ease >= 1.0 AND ease <= 3.5", name="ease_range"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    flashcard_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("flashcards.id", ondelete="CASCADE"), nullable=False
    )
    # Denormalised so the due-queue query does not need a join to filter by course.
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), index=True, nullable=False
    )

    interval_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Matches INITIAL_EASE in services/learning/scheduling.py, which owns the
    # algorithm; duplicated as a literal so the model layer imports no services.
    ease: Mapped[float] = mapped_column(Float, default=2.5, nullable=False)
    review_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lapses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True
    )
    # Null means never scheduled — a brand new card, which counts as due.
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True
    )

    user: Mapped["User"] = relationship(back_populates="review_states")
    flashcard: Mapped["Flashcard"] = relationship(back_populates="review_states")
    course: Mapped["Course"] = relationship()
    reviews: Mapped[list["FlashcardReview"]] = relationship(
        back_populates="state", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<FlashcardReviewState interval={self.interval_days}d due={self.due_at}>"


class FlashcardReview(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One rating a student gave one card at one moment. Immutable."""

    __tablename__ = "flashcard_reviews"
    __table_args__ = (Index("ix_flashcard_reviews_user_time", "user_id", "reviewed_at"),)

    state_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("flashcard_review_states.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    rating: Mapped[ReviewRating] = mapped_column(
        Enum(ReviewRating, name="review_rating", native_enum=False), nullable=False
    )
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # The interval this review produced, kept so a review history can be charted
    # without replaying the scheduler.
    interval_days_after: Mapped[int] = mapped_column(Integer, nullable=False)

    state: Mapped["FlashcardReviewState"] = relationship(back_populates="reviews")

    def __repr__(self) -> str:
        return f"<FlashcardReview {self.rating.value} -> {self.interval_days_after}d>"
