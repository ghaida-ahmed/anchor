import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, UpdatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.course import Course
    from app.models.mastery import TopicMastery


def normalise_topic_name(name: str) -> str:
    """Canonical form used to detect duplicates.

    Extraction runs against different retrieved excerpts each time, so the same
    concept can come back as "TCP Congestion Control", "tcp congestion control" or
    "TCP  Congestion Control". Collapsing case and whitespace catches those without
    trying to be clever about genuine synonyms, which would risk merging distinct
    topics.
    """
    return " ".join(name.lower().split())


class Topic(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """A concept taught by a course, derived from its uploaded material.

    Topics are the unit the adaptive engine reasons about: mastery is tracked per
    topic, quizzes are generated per topic, and recommendations name topics.

    They are derived data, but unlike chunks they are NOT disposable — mastery rows
    reference them, so regeneration deactivates rather than deletes (see
    `is_active`).
    """

    __tablename__ = "topics"
    __table_args__ = (
        # Duplicate protection at the database level, on the normalised name.
        UniqueConstraint("course_id", "normalised_name", name="uq_topics_course_name"),
        Index("ix_topics_course_id_is_active", "course_id", "is_active"),
    )

    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    # Lower-cased, whitespace-collapsed `name`. Carried as a column rather than
    # computed on read so the unique constraint can enforce it.
    normalised_name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # Regenerating topics after new uploads must not orphan a student's mastery
    # history. A topic that no longer appears in the material is deactivated: it
    # stops being offered for new quizzes, but its mastery row and the attempts
    # behind it stay intact and readable.
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    course: Mapped["Course"] = relationship(back_populates="topics")
    mastery_entries: Mapped[list["TopicMastery"]] = relationship(
        back_populates="topic",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Topic {self.name}{'' if self.is_active else ' (inactive)'}>"
