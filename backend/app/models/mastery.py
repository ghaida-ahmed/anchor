import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, UpdatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.course import Course
    from app.models.topic import Topic
    from app.models.user import User


class TopicMastery(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """One student's demonstrated command of one topic.

    Two scores are stored deliberately:

    * `raw_score` is the algorithm's state — the exponentially-weighted estimate
      updated on every answer.
    * `mastery_score` is what the student sees: `raw_score` damped by how much
      evidence exists, so a single lucky answer cannot read as mastery.

    Keeping both means the update rule stays a pure function of the previous state
    and the new answer, and the displayed value never has to be reverse-engineered.
    The formula lives in `app/services/learning/mastery.py`.
    """

    __tablename__ = "topic_mastery"
    __table_args__ = (
        UniqueConstraint("user_id", "topic_id", name="uq_topic_mastery_user_topic"),
        CheckConstraint(
            "mastery_score >= 0 AND mastery_score <= 100", name="mastery_score_range"
        ),
        CheckConstraint("raw_score >= 0 AND raw_score <= 100", name="raw_score_range"),
        CheckConstraint(
            "correct_answers >= 0 AND correct_answers <= questions_attempted",
            name="correct_within_attempted",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Denormalised from the topic so course-wide mastery is one indexed query.
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), index=True, nullable=False
    )

    mastery_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    raw_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # Quiz questions only. This is what the UI labels "questions answered", and
    # what confidence damping is primarily based on.
    questions_attempted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    correct_answers: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Flashcard reviews are weaker, self-reported evidence, so they are counted
    # separately rather than inflating the question count.
    # server_default so the column can be added to a table that already has rows.
    flashcard_reviews: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    # True when the most recent answer was wrong — the adaptive engine weights this
    # separately from the smoothed score, so a fresh mistake surfaces immediately.
    last_answer_correct: Mapped[bool | None] = mapped_column(default=None, nullable=True)
    last_practised_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True
    )

    user: Mapped["User"] = relationship(back_populates="topic_mastery")
    course: Mapped["Course"] = relationship(back_populates="topic_mastery")
    topic: Mapped["Topic"] = relationship(back_populates="mastery_entries")

    def __repr__(self) -> str:
        return f"<TopicMastery {self.mastery_score:.1f} n={self.questions_attempted}>"
