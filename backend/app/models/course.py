import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, UpdatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.flashcard import Flashcard
    from app.models.mastery import TopicMastery
    from app.models.quiz import Quiz
    from app.models.topic import Topic
    from app.models.user import User


class Course(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "courses"
    # A student should not end up with two "CS340" entries.
    __table_args__ = (
        UniqueConstraint("user_id", "code", name="uq_courses_user_id_code"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # Optional. A Date, not a timestamp: an exam happens on a day, and storing an
    # instant would invent a precision (and a timezone) the student never gave.
    exam_date: Mapped[date | None] = mapped_column(Date, default=None, nullable=True)
    # Digest of the READY documents the topic set was last extracted from. Empty
    # until the first successful extraction. Comparing it with the course's current
    # material is how ANCHOR knows whether topics are still in sync — see
    # services/learning/material.py for why this is a digest and not a timestamp.
    topics_fingerprint: Mapped[str] = mapped_column(
        String(64), default="", server_default="", nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="courses")
    documents: Mapped[list["Document"]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
    )
    topics: Mapped[list["Topic"]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
    )
    topic_mastery: Mapped[list["TopicMastery"]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
    )
    quizzes: Mapped[list["Quiz"]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
    )
    flashcards: Mapped[list["Flashcard"]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Course {self.code}>"
