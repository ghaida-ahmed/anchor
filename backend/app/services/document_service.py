"""Document business logic: validation, storage and metadata.

Phase 3 extends this service with text extraction, chunking and embedding. That
work belongs behind this boundary so the HTTP layer never learns about the
retrieval pipeline.
"""

import uuid
from dataclasses import dataclass
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import InvalidUploadError, ResourceNotFoundError
from app.models import Course, Document, DocumentFileType, ProcessingStatus
from app.services.storage import StorageService, build_storage_key

# Extension → declared content types we accept for it. The extension decides the
# type; the content type is only cross-checked, because browsers are inconsistent
# (Markdown in particular arrives as text/markdown, text/plain or nothing at all).
ALLOWED_TYPES: dict[str, DocumentFileType] = {
    "pdf": DocumentFileType.PDF,
    "txt": DocumentFileType.TXT,
    "md": DocumentFileType.MD,
}

PDF_MAGIC = b"%PDF-"


@dataclass(frozen=True)
class UploadPayload:
    """A validated upload, decoupled from FastAPI's `UploadFile`."""

    original_filename: str
    file_type: DocumentFileType
    size: int
    stream: BinaryIO


def parse_upload_filename(filename: str | None) -> tuple[str, DocumentFileType]:
    """Validate the extension and return a safe display name plus its type."""
    if not filename or "." not in filename:
        raise InvalidUploadError("The file needs a name with an extension.")

    # Strip any directory component a client may have sent before taking the stem.
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    stem, _, extension = base.rpartition(".")
    extension = extension.lower()

    file_type = ALLOWED_TYPES.get(extension)
    if file_type is None:
        supported = ", ".join(sorted(ALLOWED_TYPES)).upper()
        raise InvalidUploadError(
            f"'{extension}' files are not supported. Upload one of: {supported}."
        )

    if not stem.strip():
        raise InvalidUploadError("The file needs a name.")

    return base[:255], file_type


class DocumentService:
    def __init__(self, session: Session, storage: StorageService) -> None:
        self.session = session
        self.storage = storage

    def list_for_course(self, user_id: uuid.UUID, course_id: uuid.UUID) -> list[Document]:
        self._assert_course_owned(user_id, course_id)
        return list(
            self.session.scalars(
                select(Document)
                .where(Document.course_id == course_id)
                .order_by(Document.created_at.desc())
            )
        )

    def get(self, user_id: uuid.UUID, document_id: uuid.UUID) -> Document:
        """Ownership is enforced by joining through the owning course."""
        document = self.session.scalar(
            select(Document)
            .join(Course, Course.id == Document.course_id)
            .where(Document.id == document_id, Course.user_id == user_id)
        )
        if document is None:
            raise ResourceNotFoundError("Document", str(document_id))
        return document

    def create(
        self, user_id: uuid.UUID, course_id: uuid.UUID, payload: UploadPayload
    ) -> Document:
        self._assert_course_owned(user_id, course_id)

        if payload.size <= 0:
            raise InvalidUploadError("The file is empty.")
        if payload.size > settings.MAX_UPLOAD_BYTES:
            limit_mb = settings.MAX_UPLOAD_BYTES // (1024 * 1024)
            raise InvalidUploadError(f"Files must be {limit_mb} MB or smaller.")

        self._assert_content_matches_type(payload)

        key = build_storage_key(course_id, payload.file_type.value)
        self.storage.save(key, payload.stream)

        document = Document(
            course_id=course_id,
            filename=payload.original_filename,
            original_filename=payload.original_filename,
            file_type=payload.file_type,
            file_size=payload.size,
            storage_path=key,
            # Nothing has read the file. It waits here for Phase 3's pipeline.
            processing_status=ProcessingStatus.UPLOADED,
        )
        self.session.add(document)

        try:
            self.session.commit()
        except Exception:
            # Do not leave an orphaned file behind if the row fails to persist.
            self.session.rollback()
            self.storage.delete(key)
            raise

        self.session.refresh(document)
        return document

    def delete(self, user_id: uuid.UUID, document_id: uuid.UUID) -> None:
        document = self.get(user_id, document_id)
        key = document.storage_path

        self.session.delete(document)
        self.session.commit()

        # After the commit: a failed unlink leaves a harmless orphan file, whereas
        # deleting first would lose the file if the transaction then failed.
        self.storage.delete(key)

    def _assert_course_owned(self, user_id: uuid.UUID, course_id: uuid.UUID) -> None:
        owned = self.session.scalar(
            select(Course.id).where(Course.id == course_id, Course.user_id == user_id)
        )
        if owned is None:
            raise ResourceNotFoundError("Course", str(course_id))

    @staticmethod
    def _assert_content_matches_type(payload: UploadPayload) -> None:
        """Cheap sniff so a renamed binary cannot pose as a PDF.

        Not a security boundary — it is a correctness check that saves Phase 3's
        extractor from files it can never parse.
        """
        if payload.file_type is not DocumentFileType.PDF:
            return

        head = payload.stream.read(len(PDF_MAGIC))
        payload.stream.seek(0)
        if head != PDF_MAGIC:
            raise InvalidUploadError("That file is not a valid PDF.")
