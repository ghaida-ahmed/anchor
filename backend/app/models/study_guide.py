import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, UpdatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.course import Course
    from app.models.document import Document
    from app.models.document_chunk import DocumentChunk
    from app.models.topic import Topic
    from app.models.user import User


class StudyGuideStatus(str, enum.Enum):
    NOT_GENERATED = "not_generated"
    GENERATING = "generating"
    READY = "ready"
    # The material or topic set has changed since generation. The guide is still
    # readable — it is simply no longer known to match the course.
    STALE = "stale"
    FAILED = "failed"


class StudyGuide(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """A persisted, grounded guide to one course.

    Stored rather than generated on demand: a guide costs one model call per topic,
    and regenerating it on every page view would be indefensible. Regeneration is
    always an explicit user action.

    Learning state is NOT stored here. Mastery badges are overlaid at read time from
    the mastery services, so the text stays put while the student's progress moves.
    """

    __tablename__ = "study_guides"
    __table_args__ = (
        UniqueConstraint("user_id", "course_id", name="uq_study_guide_user_course"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[StudyGuideStatus] = mapped_column(
        Enum(StudyGuideStatus, name="study_guide_status", native_enum=False),
        default=StudyGuideStatus.NOT_GENERATED,
        server_default=StudyGuideStatus.NOT_GENERATED.name,
        nullable=False,
    )
    overview: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # Key terms drawn from the material, as
    # [{term, definition, chunk_id, document_id}]. Excerpt numbers are
    # resolved to real chunk ids before storage — a number is only meaningful
    # inside the prompt that produced it.
    key_terms: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True
    )
    # Digest of the ready documents and active topics the guide was built from.
    # A mismatch on read means the course moved on: the guide is marked stale rather
    # than silently regenerated.
    material_fingerprint: Mapped[str] = mapped_column(
        String(64), default="", nullable=False
    )
    # Student-safe message when status is FAILED.
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    user: Mapped["User"] = relationship()
    course: Mapped["Course"] = relationship()
    sections: Mapped[list["StudyGuideSection"]] = relationship(
        back_populates="guide",
        cascade="all, delete-orphan",
        order_by="StudyGuideSection.position",
    )

    def __repr__(self) -> str:
        return f"<StudyGuide {self.status.value}>"


class StudyGuideSection(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One topic's section of the guide."""

    __tablename__ = "study_guide_sections"
    __table_args__ = (Index("ix_study_guide_sections_guide", "guide_id", "position"),)

    guide_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("study_guides.id", ondelete="CASCADE"), nullable=False
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), index=True, nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    key_concepts: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    guide: Mapped["StudyGuide"] = relationship(back_populates="sections")
    topic: Mapped["Topic"] = relationship()
    sources: Mapped[list["StudyGuideSectionSource"]] = relationship(
        back_populates="section", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<StudyGuideSection {self.position}>"


class StudyGuideSectionSource(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A chunk a section was written from.

    An association table rather than a JSON list of ids, so provenance participates
    in the same cascade and integrity rules as every other citation in ANCHOR.
    """

    __tablename__ = "study_guide_section_sources"
    __table_args__ = (
        UniqueConstraint("section_id", "chunk_id", name="uq_section_source_chunk"),
    )

    section_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("study_guide_sections.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )

    section: Mapped["StudyGuideSection"] = relationship(back_populates="sources")
    chunk: Mapped["DocumentChunk"] = relationship()
    document: Mapped["Document"] = relationship()
