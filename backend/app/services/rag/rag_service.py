"""RAG orchestration: question in, grounded answer plus citations out.

The sequence is deliberately linear and readable:

    validate ownership
      -> embed the question
      -> retrieve owned, in-course, ready chunks
      -> stop if nothing is relevant enough      (no LLM call)
      -> build context within the token budget
      -> generate
      -> attach citations from the DATABASE rows

Citations never come from the model's output. The model is told not to write them,
and the application builds them from the chunks it actually put in the prompt — so a
page number cannot be hallucinated.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ResourceNotFoundError
from app.models import Course
from app.services.rag.embeddings import EmbeddingProvider
from app.services.rag.generation import (
    INSUFFICIENT_CONTEXT_ANSWER,
    LLMProvider,
    build_context,
    build_messages,
)
from app.services.rag.retrieval import RetrievalService, RetrievedChunk


@dataclass(frozen=True)
class Citation:
    """Provenance for an answer. Every field is read from a stored chunk."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    page_number: int
    excerpt: str


@dataclass(frozen=True)
class Answer:
    answer: str
    citations: list[Citation]
    # False when retrieval found nothing relevant enough and no model was called.
    is_grounded: bool


# How much of a chunk to echo back as the citation excerpt. Enough to recognise the
# passage, short enough not to reproduce the document in the API response.
EXCERPT_CHARS = 240


def _drop_weak_matches(
    chunks: list[RetrievedChunk], margin: float
) -> list[RetrievedChunk]:
    """Keep only chunks close to the best match.

    Retrieval returns a *ranked* list, not a relevance verdict: `top_k` is filled
    with the closest chunks available, so on a narrow question the tail can be
    unrelated material that merely scored above the absolute floor. Those chunks
    dilute the context, and citing them tells the student that a document supported
    an answer it had nothing to do with.

    Chunks arrive best-first, so this is a prefix.
    """
    if not chunks:
        return []

    cutoff = chunks[0].similarity - margin
    return [chunk for chunk in chunks if chunk.similarity >= cutoff]


def _to_citation(chunk: RetrievedChunk) -> Citation:
    excerpt = " ".join(chunk.content.split())
    if len(excerpt) > EXCERPT_CHARS:
        excerpt = f"{excerpt[:EXCERPT_CHARS].rstrip()}…"

    return Citation(
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        document_name=chunk.document_name,
        page_number=chunk.page_number,
        excerpt=excerpt,
    )


class RagService:
    def __init__(
        self,
        session: Session,
        embeddings: EmbeddingProvider,
        llm: LLMProvider,
    ) -> None:
        self.session = session
        self.retrieval = RetrievalService(session)
        self.embeddings = embeddings
        self.llm = llm

    def search(
        self, user_id: uuid.UUID, course_id: uuid.UUID, query: str, top_k: int
    ) -> list[RetrievedChunk]:
        """Semantic search on its own, with no generation. Also the endpoint used
        to sanity-check retrieval quality independently of the model."""
        self._assert_course_owned(user_id, course_id)
        embedding = self.embeddings.embed_query(query)
        # No similarity floor here: search is a diagnostic surface and seeing weak
        # matches with their scores is the point.
        return self.retrieval.search(user_id, course_id, embedding, top_k)

    def ask(self, user_id: uuid.UUID, course_id: uuid.UUID, question: str) -> Answer:
        self._assert_course_owned(user_id, course_id)

        embedding = self.embeddings.embed_query(question)
        chunks = self.retrieval.search(
            user_id,
            course_id,
            embedding,
            top_k=settings.RAG_TOP_K_DEFAULT,
            min_similarity=settings.RAG_MIN_SIMILARITY,
        )

        # Nothing cleared the relevance floor. Answering anyway would mean answering
        # from the model's general knowledge while implying the course material
        # supports it — so no request is made, which also costs nothing.
        if not chunks:
            return Answer(
                answer=INSUFFICIENT_CONTEXT_ANSWER, citations=[], is_grounded=False
            )

        relevant = _drop_weak_matches(chunks, settings.RAG_CITATION_MARGIN)
        context, used = build_context(relevant, settings.RAG_MAX_CONTEXT_TOKENS)
        if not used:
            return Answer(
                answer=INSUFFICIENT_CONTEXT_ANSWER, citations=[], is_grounded=False
            )

        answer = self.llm.generate(build_messages(question, context))

        # Citations describe exactly the excerpts the model was shown.
        return Answer(
            answer=answer,
            citations=[_to_citation(chunk) for chunk in used],
            is_grounded=True,
        )

    def ready_chunk_count(self, user_id: uuid.UUID, course_id: uuid.UUID) -> int:
        self._assert_course_owned(user_id, course_id)
        return self.retrieval.count_ready_chunks(user_id, course_id)

    def _assert_course_owned(self, user_id: uuid.UUID, course_id: uuid.UUID) -> None:
        """Belt and braces. Retrieval already filters by owner inside its query;
        this makes a request for someone else's course a clean 404 rather than an
        empty result set that looks like an unhelpful course."""
        owned = self.session.scalar(
            select(Course.id).where(Course.id == course_id, Course.user_id == user_id)
        )
        if owned is None:
            raise ResourceNotFoundError("Course", str(course_id))
