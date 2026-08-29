import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, UpdatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.course import Course
    from app.models.document_chunk import DocumentChunk


class DocumentFileType(str, enum.Enum):
    """Formats ANCHOR accepts. Deliberately narrow: every entry here must have a
    working text extractor by Phase 3, so nothing is added speculatively."""

    PDF = "pdf"
    TXT = "txt"
    MD = "md"


class ProcessingStatus(str, enum.Enum):
    """Lifecycle of a document through the (future) ingestion pipeline.

    Phase 2 only ever produces `UPLOADED`. Nothing sets `PROCESSING` or `READY`
    until extraction exists in Phase 3 — a freshly uploaded file must not claim to
    have been analysed.
    """

    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class Document(UUIDPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """An uploaded course file.

    Extracted text lives in `document_chunks`, one row per retrievable slice, each
    carrying its page number so answers can cite it.
    """

    __tablename__ = "documents"

    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # Display name, sanitised. `original_filename` keeps exactly what the user sent.
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[DocumentFileType] = mapped_column(
        Enum(DocumentFileType, name="document_file_type", native_enum=False),
        nullable=False,
    )
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Opaque key for the storage backend — a relative path today, an object key
    # later. Route handlers never interpret it; only StorageService does.
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        Enum(ProcessingStatus, name="processing_status", native_enum=False),
        default=ProcessingStatus.UPLOADED,
        # `.name`, not `.value`: SQLAlchemy's Enum stores and reads member NAMES
        # ("UPLOADED"), so a server_default of "uploaded" produces rows the ORM
        # then refuses to load. Corrected in migration c1f83d5a47b2.
        server_default=ProcessingStatus.UPLOADED.name,
        nullable=False,
    )
    # Why processing failed, phrased for the student. Never a stack trace: this
    # value is returned by the API.
    processing_error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    course: Mapped["Course"] = relationship(back_populates="documents")
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Document {self.filename} ({self.processing_status.value})>"
