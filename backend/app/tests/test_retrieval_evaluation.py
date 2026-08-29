"""Retrieval over a realistic multi-document corpus.

This pins the behaviour that must hold regardless of embedding provider: the right
document is reachable in the top few results, and questions the corpus does not
cover fall below the relevance threshold.

It deliberately does NOT assert on paraphrased questions. Automated runs use the
lexical fake provider, which cannot match "turn a website name into a numeric
address" to "resolves domain names into IP addresses". Semantic quality is measured
separately by `scripts/evaluate_retrieval.py` against the real API.
"""

import uuid

import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    Course,
    Document,
    DocumentChunk,
    DocumentFileType,
    ProcessingStatus,
    User,
)
from app.services.rag.chunking import chunk_pages
from app.services.rag.extraction import ExtractedPage
from app.services.rag.retrieval import RetrievalService
from app.tests.evaluation.corpus import CORPUS, OUT_OF_SCOPE_QUESTIONS, QUESTIONS
from app.tests.fakes import FakeEmbeddingProvider


@pytest.fixture
def corpus(
    session: Session, embeddings: FakeEmbeddingProvider
) -> tuple[uuid.UUID, uuid.UUID]:
    """Ingest the evaluation corpus directly, bypassing upload and extraction."""
    user = User(
        name="Eval Student",
        email=f"eval-{uuid.uuid4().hex[:8]}@university.edu",
        hashed_password="not-a-real-hash",
    )
    course = Course(title="Computer Networks", code="EVAL1", description="")
    user.courses.append(course)
    session.add(user)
    session.flush()

    for filename, pages in CORPUS:
        document = Document(
            course_id=course.id,
            filename=filename,
            original_filename=filename,
            file_type=DocumentFileType.PDF,
            file_size=sum(len(page) for page in pages),
            storage_path=f"eval/{uuid.uuid4().hex}.pdf",
            processing_status=ProcessingStatus.READY,
        )
        session.add(document)
        session.flush()

        chunks = chunk_pages(
            [ExtractedPage(page_number=i, text=t) for i, t in enumerate(pages, start=1)]
        )
        vectors = embeddings.embed_documents([chunk.content for chunk in chunks])
        session.add_all(
            [
                DocumentChunk(
                    document_id=document.id,
                    chunk_index=chunk.chunk_index,
                    page_number=chunk.page_number,
                    content=chunk.content,
                    token_count=chunk.token_count,
                    embedding=vector,
                )
                for chunk, vector in zip(chunks, vectors, strict=True)
            ]
        )

    session.flush()
    return user.id, course.id


DIRECT_QUESTIONS = [item for item in QUESTIONS if not item.paraphrased]


@pytest.mark.parametrize(
    "item", DIRECT_QUESTIONS, ids=[item.question[:40] for item in DIRECT_QUESTIONS]
)
def test_direct_questions_retrieve_the_right_document(
    session: Session,
    embeddings: FakeEmbeddingProvider,
    corpus: tuple[uuid.UUID, uuid.UUID],
    item,
) -> None:
    user_id, course_id = corpus
    retrieval = RetrievalService(session)

    results = retrieval.search(
        user_id, course_id, embeddings.embed_query(item.question), top_k=5
    )

    assert results, "retrieval returned nothing for a question the corpus answers"
    assert item.expected_document in {chunk.document_name for chunk in results}


def test_retrieval_spans_multiple_documents(
    session: Session,
    embeddings: FakeEmbeddingProvider,
    corpus: tuple[uuid.UUID, uuid.UUID],
) -> None:
    """The corpus is four documents; retrieval must not be pinned to just one."""
    user_id, course_id = corpus
    retrieval = RetrievalService(session)

    seen: set[str] = set()
    for item in QUESTIONS:
        results = retrieval.search(
            user_id, course_id, embeddings.embed_query(item.question), top_k=3
        )
        seen.update(chunk.document_name for chunk in results)

    assert len(seen) >= 3


@pytest.mark.parametrize("question", OUT_OF_SCOPE_QUESTIONS)
def test_out_of_scope_questions_fall_below_the_threshold(  # noqa: D401
    session: Session,
    embeddings: FakeEmbeddingProvider,
    corpus: tuple[uuid.UUID, uuid.UUID],
    question: str,
) -> None:
    """Nothing clears the bar, so `ask` declines instead of calling the model.

    Runs against the lexical fake at its own calibrated floor (see conftest). The
    fake's on- and off-topic ranges overlap, so this proves the *mechanism* — that
    a sub-threshold result set comes back empty — not the discrimination quality,
    which only the real provider can demonstrate.
    """
    user_id, course_id = corpus
    retrieval = RetrievalService(session)

    above_threshold = retrieval.search(
        user_id,
        course_id,
        embeddings.embed_query(question),
        top_k=5,
        min_similarity=settings.RAG_MIN_SIMILARITY,
    )

    assert above_threshold == []


def test_chunk_provenance_survives_ingestion(
    session: Session,
    embeddings: FakeEmbeddingProvider,
    corpus: tuple[uuid.UUID, uuid.UUID],
) -> None:
    user_id, course_id = corpus
    retrieval = RetrievalService(session)

    results = retrieval.search(
        user_id, course_id, embeddings.embed_query("stack canary return address"), top_k=5
    )

    for chunk in results:
        assert chunk.document_name.endswith(".pdf")
        assert chunk.page_number >= 1
        assert chunk.content
