import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.course import Course
    from app.models.document import Document
    from app.models.document_chunk import DocumentChunk
    from app.models.topic import Topic


class RelationshipType(str, enum.Enum):
    """How two topics relate, as inferred from the course's own material.

    `PREREQUISITE` is directional: source must be understood before target.
    `RELATED` is symmetric, and stored once — see the reverse-duplicate guard in
    the service.

    These are INFERRED relationships, not a claim about pedagogy. The material
    presents one idea as building on another; that is all the edge asserts.
    """

    PREREQUISITE = "prerequisite"
    RELATED = "related"


class TopicRelationship(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """An edge in a course's knowledge map."""

    __tablename__ = "topic_relationships"
    __table_args__ = (
        UniqueConstraint(
            "source_topic_id",
            "target_topic_id",
            "relationship_type",
            name="uq_topic_relationship_pair",
        ),
        # A topic cannot be its own prerequisite. Enforced in the database as well
        # as the service, because it is cheap and absolute.
        CheckConstraint("source_topic_id <> target_topic_id", name="no_self_edge"),
        Index("ix_topic_relationships_course_type", "course_id", "relationship_type"),
        Index("ix_topic_relationships_target", "target_topic_id"),
    )

    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    source_topic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), index=True, nullable=False
    )
    target_topic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), nullable=False
    )
    relationship_type: Mapped[RelationshipType] = mapped_column(
        Enum(RelationshipType, name="relationship_type", native_enum=False),
        nullable=False,
    )
    # How many distinct chunks support this edge. An evidence count, NOT a
    # model-reported probability: the number means "N excerpts mention both", which
    # a student can check, rather than a confidence we cannot calibrate.
    supporting_chunk_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    course: Mapped["Course"] = relationship()
    source_topic: Mapped["Topic"] = relationship(foreign_keys=[source_topic_id])
    target_topic: Mapped["Topic"] = relationship(foreign_keys=[target_topic_id])
    evidence: Mapped[list["TopicRelationshipEvidence"]] = relationship(
        back_populates="topic_relationship", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<TopicRelationship {self.relationship_type.value}>"


class TopicRelationshipEvidence(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A chunk that supports one relationship.

    Foreign keys to the real rows, so the document name and page are read at render
    time and can never have been invented by the model.
    """

    __tablename__ = "topic_relationship_evidence"
    __table_args__ = (
        UniqueConstraint(
            "relationship_id", "chunk_id", name="uq_relationship_evidence_chunk"
        ),
    )

    relationship_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("topic_relationships.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )

    topic_relationship: Mapped["TopicRelationship"] = relationship(
        back_populates="evidence"
    )
    chunk: Mapped["DocumentChunk"] = relationship()
    document: Mapped["Document"] = relationship()

    def __repr__(self) -> str:
        return f"<TopicRelationshipEvidence chunk={self.chunk_id}>"
