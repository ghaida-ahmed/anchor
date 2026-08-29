"""Ownership-scoped semantic retrieval.

This module holds the one query in ANCHOR where a mistake leaks another student's
material into an answer, so it is kept small and deliberately explicit.

The rule: **ownership is a predicate inside the same statement as the vector
search.** The query joins

    document_chunks -> documents -> courses -> courses.user_id = :user_id

and applies that filter in the WHERE clause, so PostgreSQL restricts the candidate
set *before* ordering by distance and applying LIMIT. Retrieving a global top-k and
discarding other users' rows in Python would be wrong twice over: it reads data the
caller may not see, and it silently returns fewer (or zero) results because the
budget was spent on rows that were then thrown away.

Distance metric: cosine (`<=>`, `vector_cosine_ops`). OpenAI embeddings are
unit-normalised, so cosine and inner product rank identically — but cosine distance
is bounded [0, 2], which makes `similarity = 1 - distance` a stable number in
[-1, 1] to threshold on. Inner product has no such bound.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Course, Document, DocumentChunk, ProcessingStatus


@dataclass(frozen=True)
class RetrievedChunk:
    """A chunk plus the provenance a citation needs."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    page_number: int
    chunk_index: int
    content: str
    # Cosine similarity in [-1, 1]; 1 is identical. Derived as 1 - cosine distance.
    similarity: float

    @property
    def distance(self) -> float:
        return 1.0 - self.similarity


class RetrievalService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _scoped_query(
        self, user_id: uuid.UUID, course_id: uuid.UUID, embedding: list[float]
    ) -> Select:
        """Build the ownership- and course-scoped similarity query.

        Every filter here is load-bearing:

        * `Course.user_id == user_id` — the ownership boundary.
        * `Document.course_id == course_id` — a question in course A must never
          reach course B's material. Cross-course retrieval is not a Phase 3
          feature, so this is unconditional.
        * `processing_status == READY` — chunks from a half-processed document
          would give partial, misleading answers.
        """
        distance = DocumentChunk.embedding.cosine_distance(embedding)

        return (
            select(
                DocumentChunk.id,
                DocumentChunk.document_id,
                Document.filename,
                DocumentChunk.page_number,
                DocumentChunk.chunk_index,
                DocumentChunk.content,
                distance.label("distance"),
            )
            .join(Document, Document.id == DocumentChunk.document_id)
            .join(Course, Course.id == Document.course_id)
            .where(
                Course.user_id == user_id,
                Course.id == course_id,
                Document.processing_status == ProcessingStatus.READY,
            )
            .order_by(distance)
        )

    def search(
        self,
        user_id: uuid.UUID,
        course_id: uuid.UUID,
        embedding: list[float],
        top_k: int,
        min_similarity: float | None = None,
    ) -> list[RetrievedChunk]:
        """Return the `top_k` most similar chunks the user owns in this course.

        `min_similarity` filters after ranking — unlike ownership, it is a quality
        threshold, not a security boundary, and dropping weak matches from an
        already-correct result set is safe.
        """
        bounded_k = max(1, min(top_k, settings.RAG_TOP_K_MAX))

        rows = self.session.execute(
            self._scoped_query(user_id, course_id, embedding).limit(bounded_k)
        ).all()

        results = [
            RetrievedChunk(
                chunk_id=row.id,
                document_id=row.document_id,
                document_name=row.filename,
                page_number=row.page_number,
                chunk_index=row.chunk_index,
                content=row.content,
                similarity=1.0 - float(row.distance),
            )
            for row in rows
        ]

        if min_similarity is None:
            return results
        return [chunk for chunk in results if chunk.similarity >= min_similarity]

    def count_ready_chunks(self, user_id: uuid.UUID, course_id: uuid.UUID) -> int:
        """How many searchable chunks the course has — used to tell an empty
        course apart from a question the material simply does not cover."""
        from sqlalchemy import func

        return (
            self.session.scalar(
                select(func.count(DocumentChunk.id))
                .join(Document, Document.id == DocumentChunk.document_id)
                .join(Course, Course.id == Document.course_id)
                .where(
                    Course.user_id == user_id,
                    Course.id == course_id,
                    Document.processing_status == ProcessingStatus.READY,
                )
            )
            or 0
        )
