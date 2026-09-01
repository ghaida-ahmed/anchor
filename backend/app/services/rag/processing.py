"""Turning an uploaded document into searchable chunks.

Runs in a FastAPI background task after the upload response has been sent, so a
20-page PDF does not hold the request open. That means it cannot reuse the request's
session — that session is closed by then — so a session factory is injected and the
task owns its own transaction.

Status transitions, and nothing else:

    uploaded -> processing -> ready
    uploaded -> processing -> failed

A document is only ever `ready` once its chunks are committed. There is no path
that reports success without them.
"""

import logging
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AnchorError
from app.models import Document, DocumentChunk, ProcessingStatus
from app.services.rag.chunking import chunk_pages
from app.services.rag.embeddings import EmbeddingProvider
from app.services.rag.extraction import ExtractionError, get_extractor
from app.services.rag.generation import LLMProvider
from app.services.storage import StorageService

logger = logging.getLogger(__name__)

# `processing_error` is 500 characters and is returned by the API.
MAX_ERROR_CHARS = 400

SessionFactory = Callable[[], AbstractContextManager[Session]]
EmbeddingProviderFactory = Callable[[], EmbeddingProvider]
LLMProviderFactory = Callable[[], "LLMProvider"]


class DocumentProcessor:
    """Extraction → chunking → embeddings → persistence, with status bookkeeping."""

    def __init__(
        self,
        session_factory: SessionFactory,
        storage: StorageService,
        embeddings_factory: EmbeddingProviderFactory,
        llm_factory: "LLMProviderFactory | None" = None,
    ) -> None:
        self.session_factory = session_factory
        self.storage = storage
        # Topic extraction needs a generation provider. Optional: without one the
        # document still processes and only the automatic topic step is skipped,
        # which the "Update topics" action then covers.
        self.llm_factory = llm_factory
        # A factory, not an instance: constructing the provider fails when no API
        # key is set, and that must mark the document failed — not break the upload
        # request that scheduled this task.
        self.embeddings_factory = embeddings_factory

    def process(self, document_id: uuid.UUID, *, force: bool = False) -> None:
        """Entry point for the background task.

        Never raises: a background task has nobody to report to, so failures are
        recorded on the document row and logged. The client learns about them by
        polling the document's `processing_status`.
        """
        try:
            self._process(document_id, force=force)
        except Exception:
            logger.exception("Processing failed for document %s", document_id)
            self._record_failure(
                document_id,
                "The document could not be processed. Please try uploading it again.",
            )

    def _process(self, document_id: uuid.UUID, *, force: bool) -> None:
        with self.session_factory() as session:
            document = session.get(Document, document_id)
            if document is None:
                logger.warning("Document %s vanished before processing", document_id)
                return

            # Re-embedding an unchanged document costs money for an identical
            # result. Uploads are immutable, so `ready` means there is nothing to do.
            if document.processing_status is ProcessingStatus.READY and not force:
                return

            storage_key = document.storage_path
            file_type = document.file_type

            document.processing_status = ProcessingStatus.PROCESSING
            document.processing_error = None
            session.commit()

        try:
            if not self.storage.exists(storage_key):
                raise ExtractionError("The stored file is missing.")

            # `local_path` is a context manager because an object-store backend
            # downloads to a temp file here. Exiting the block removes it, so a
            # failed extraction cannot leave a copy of the student's document
            # behind in the container's temp directory.
            with self.storage.local_path(storage_key) as path:
                pages = get_extractor(file_type).extract(path)

            chunks = chunk_pages(pages)
            if not chunks:
                raise ExtractionError("No readable text was found in this document.")

            embeddings = self.embeddings_factory()
            vectors = embeddings.embed_documents([chunk.content for chunk in chunks])

        except AnchorError as error:
            # Extraction and embedding errors carry messages written for a student.
            self._record_failure(document_id, str(error))
            return

        with self.session_factory() as session:
            document = session.get(Document, document_id)
            if document is None:
                return

            # Reprocessing replaces the whole set; a partial mix of old and new
            # chunks would be worse than either.
            session.execute(
                delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
            )
            session.add_all(
                [
                    DocumentChunk(
                        document_id=document_id,
                        chunk_index=chunk.chunk_index,
                        page_number=chunk.page_number,
                        content=chunk.content,
                        token_count=chunk.token_count,
                        embedding=vector,
                    )
                    for chunk, vector in zip(chunks, vectors, strict=True)
                ]
            )
            # Chunks and the `ready` flag land in the same transaction, so the
            # status can never claim readiness the data does not back up.
            document.processing_status = ProcessingStatus.READY
            document.processing_error = None
            course_id = document.course_id
            user_id = document.course.user_id
            session.commit()

        # The document is READY and committed before this runs, so a topic failure
        # can never un-ready it. This is the step that makes topic extraction
        # automatic instead of a manual prerequisite the student has to know about.
        self._sync_topics(user_id, course_id, document_id)

        logger.info(
            "Processed document %s into %d chunks across %d pages",
            document_id,
            len(chunks),
            len({chunk.page_number for chunk in chunks}),
        )

    def _sync_topics(
        self, user_id: uuid.UUID, course_id: uuid.UUID, document_id: uuid.UUID
    ) -> None:
        """Bring the course's topics in line with its material.

        Deliberately best-effort. A failure here — no API key, a provider outage, a
        course whose material yields no clear topics — must leave the document
        READY and the existing topics untouched. The course simply stays flagged as
        out of sync, and the student can retry with "Update topics".
        """
        if not settings.TOPIC_AUTO_SYNC:
            return
        if self.llm_factory is None:
            logger.info(
                "Skipping topic sync for document %s: no generation provider configured",
                document_id,
            )
            return

        try:
            from app.services.learning.topic_service import TopicService

            with self.session_factory() as session:
                extracted = TopicService(session, self.llm_factory()).sync(
                    user_id, course_id
                )
            logger.info(
                "Topic sync for course %s after document %s: %s",
                course_id,
                document_id,
                "extracted" if extracted else "already current",
            )
        except Exception:
            # Never re-raised: the document is already READY and correct.
            logger.warning(
                "Topic sync failed for course %s after document %s; "
                "topics remain out of sync and can be updated manually",
                course_id,
                document_id,
                exc_info=True,
            )

    def _record_failure(self, document_id: uuid.UUID, message: str) -> None:
        try:
            with self.session_factory() as session:
                document = session.get(Document, document_id)
                if document is None:
                    return
                # Drop any chunks written before the failure so a `failed` document
                # can never contribute to retrieval.
                session.execute(
                    delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
                )
                document.processing_status = ProcessingStatus.FAILED
                document.processing_error = message[:MAX_ERROR_CHARS]
                session.commit()
        except Exception:
            logger.exception("Could not record failure for document %s", document_id)


def documents_pending_processing(session: Session, course_id: uuid.UUID) -> int:
    """How many of a course's documents are not yet finished."""
    return len(
        session.scalars(
            select(Document.id).where(
                Document.course_id == course_id,
                Document.processing_status.in_(
                    [ProcessingStatus.UPLOADED, ProcessingStatus.PROCESSING]
                ),
            )
        ).all()
    )
