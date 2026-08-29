import uuid
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.db.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.document import Document


class DocumentChunk(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A retrievable slice of a document, with its embedding.

    Chunks are derived data: they are deleted and rebuilt whenever a document is
    reprocessed, and cascade away with their document (and so with their course
    and user). Nothing else references them.

    The embedding dimension is fixed by the model named in `EMBEDDING_MODEL`.
    Vectors produced by different models are not comparable, so switching models
    requires a migration that alters this column plus a full re-embed.
    """

    __tablename__ = "document_chunks"
    __table_args__ = (
        # Retrieval narrows by document set first, then orders by distance. This
        # composite leads with document_id, so it also serves lookups by document
        # alone — a separate single-column index would be redundant.
        Index("ix_document_chunks_document_id_chunk_index", "document_id", "chunk_index"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Position within the document, across all pages. Deterministic ordering.
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # 1-based; what a citation displays.
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(settings.EMBEDDING_DIMENSIONS), nullable=False
    )

    document: Mapped["Document"] = relationship(back_populates="chunks")

    def __repr__(self) -> str:
        return f"<DocumentChunk {self.chunk_index} p{self.page_number}>"
