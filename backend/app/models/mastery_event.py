import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, Float, ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin
from app.models.quiz import Difficulty

if TYPE_CHECKING:
    from app.models.course import Course
    from app.models.topic import Topic
    from app.models.user import User


class MasteryEventSource(str, enum.Enum):
    QUIZ_ANSWER = "quiz_answer"
    FLASHCARD_REVIEW = "flashcard_review"


class MasteryEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One recorded change in a student's mastery of a topic.

    Event-sourced, not snapshotted: a row exists only where something actually
    happened. There is no daily job writing "still 62 today" for every topic, which
    would grow without bound and record nothing.

    Rows are IMMUTABLE. `effective_mastery_at_event` is stored rather than
    recomputed on read precisely so that changing the decay heuristic later cannot
    silently rewrite history — a chart of last month stays what the student was
    actually shown.
    """

    __tablename__ = "mastery_events"
    __table_args__ = (
        # The access pattern is "this topic's history, oldest first" and "this
        # course's recent activity".
        Index("ix_mastery_events_topic_time", "user_id", "topic_id", "created_at"),
        Index("ix_mastery_events_course_time", "user_id", "course_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), nullable=False
    )

    source_type: Mapped[MasteryEventSource] = mapped_column(
        Enum(MasteryEventSource, name="mastery_event_source", native_enum=False),
        nullable=False,
    )
    # The quiz answer or flashcard review behind this change. Nullable and not a
    # foreign key: history must survive the deletion of the quiz it came from.
    source_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    previous_raw_score: Mapped[float] = mapped_column(Float, nullable=False)
    new_raw_score: Mapped[float] = mapped_column(Float, nullable=False)
    previous_mastery: Mapped[float] = mapped_column(Float, nullable=False)
    new_mastery: Mapped[float] = mapped_column(Float, nullable=False)
    # What the decay heuristic said at the moment of the event, frozen.
    effective_mastery_at_event: Mapped[float] = mapped_column(Float, nullable=False)

    was_correct: Mapped[bool | None] = mapped_column(default=None, nullable=True)
    difficulty: Mapped[Difficulty | None] = mapped_column(
        Enum(Difficulty, name="difficulty", native_enum=False), nullable=True
    )
    # Cumulative counters at the time of the event, so a trend can be drawn without
    # replaying every prior row.
    questions_attempted_after: Mapped[int] = mapped_column(Integer, nullable=False)

    user: Mapped["User"] = relationship()
    course: Mapped["Course"] = relationship()
    topic: Mapped["Topic"] = relationship()

    def __repr__(self) -> str:
        return (
            f"<MasteryEvent {self.previous_mastery:.1f}->{self.new_mastery:.1f} "
            f"({self.source_type.value})>"
        )
