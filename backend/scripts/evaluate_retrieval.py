#!/usr/bin/env python
"""Retrieval quality harness.

Ingests a small course corpus, runs a set of student-phrased questions against it,
and reports hit@1, hit@3 and MRR — the question being whether the right passage is
retrieved, independently of what any language model then does with it.

Which embedding provider is used is decided by the environment, and the report says
which one ran:

  * provider key set    -> the configured real provider (Gemini by default). This
    is a genuine test of semantic retrieval.
  * unset               -> the deterministic fake from app.tests.fakes. The fake is
    lexical (hashed bag-of-words), so it exercises the pipeline and the SQL but
    CANNOT demonstrate paraphrase matching. Paraphrased questions are expected to
    score poorly, and the report labels them.

Usage, from backend/ with the venv active:

    python scripts/evaluate_retrieval.py

Writes to a scratch database (EVAL_DATABASE_URL, default anchor_eval) and drops its
own rows afterwards. It never touches the development database.
"""

import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.models import (  # noqa: E402
    Course,
    Document,
    DocumentChunk,
    DocumentFileType,
    ProcessingStatus,
    User,
)
from app.services.rag.chunking import chunk_pages  # noqa: E402
from app.services.rag.extraction import ExtractedPage  # noqa: E402
from app.services.rag.retrieval import RetrievalService  # noqa: E402
from app.tests.evaluation.corpus import (  # noqa: E402
    CORPUS,
    OUT_OF_SCOPE_QUESTIONS,
    QUESTIONS,
)

EVAL_DATABASE_URL = os.getenv(
    "EVAL_DATABASE_URL",
    "postgresql+psycopg://anchor:anchor@localhost:5432/anchor_eval",
)


def build_provider() -> tuple[object, str]:
    """The configured provider when its key is present, otherwise the fake."""
    from app.services.rag.embeddings import (
        ProviderNotConfiguredError,
        get_embedding_provider,
    )

    try:
        provider = get_embedding_provider()
    except ProviderNotConfiguredError:
        from app.tests.fakes import FakeEmbeddingProvider

        return FakeEmbeddingProvider(), "FakeEmbeddingProvider (lexical, NOT semantic)"

    return provider, f"{settings.EMBEDDING_PROVIDER} {settings.embedding_model} (real)"


def ingest(session: Session, provider, course_id: uuid.UUID) -> int:
    total = 0
    for filename, pages in CORPUS:
        document = Document(
            course_id=course_id,
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
            [
                ExtractedPage(page_number=index, text=text)
                for index, text in enumerate(pages, 1)
            ]
        )
        vectors = provider.embed_documents([chunk.content for chunk in chunks])
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
        total += len(chunks)
    session.commit()
    return total


def main() -> int:
    provider, provider_label = build_provider()

    engine = create_engine(EVAL_DATABASE_URL)
    try:
        with engine.connect() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            connection.commit()
    except Exception as error:
        print(f"Could not reach {EVAL_DATABASE_URL}: {error}")
        print(
            "Create it with: docker compose exec db psql -U anchor -d postgres "
            '-c "CREATE DATABASE anchor_eval"'
        )
        return 1

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    print("=" * 78)
    print("ANCHOR retrieval evaluation")
    print(f"  provider   : {provider_label}")
    chunking = f"{settings.CHUNK_TOKENS} tokens / {settings.CHUNK_OVERLAP_TOKENS} overlap"
    print(f"  chunking   : {chunking}")
    print(f"  threshold  : similarity >= {settings.RAG_MIN_SIMILARITY}")
    print("=" * 78)

    with Session(engine) as session:
        user = User(
            name="Eval",
            email=f"eval-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password="x",
        )
        course = Course(title="Computer Networks", code="EVAL1", description="")
        user.courses.append(course)
        session.add(user)
        session.flush()

        chunk_count = ingest(session, provider, course.id)
        print(f"\nIngested {len(CORPUS)} documents into {chunk_count} chunks.\n")

        retrieval = RetrievalService(session)
        hits_at_1 = hits_at_3 = 0
        reciprocal_ranks = []

        header = f"{'':2} {'Q':<58} {'rank':>4} {'sim':>6}"
        print(header)
        print("-" * len(header))

        for item in QUESTIONS:
            embedding = provider.embed_query(item.question)
            results = retrieval.search(user.id, course.id, embedding, top_k=5)

            rank = next(
                (
                    position
                    for position, chunk in enumerate(results, start=1)
                    if chunk.document_name == item.expected_document
                    and chunk.page_number == item.expected_page
                ),
                None,
            )

            if rank == 1:
                hits_at_1 += 1
            if rank is not None and rank <= 3:
                hits_at_3 += 1
            reciprocal_ranks.append(1 / rank if rank else 0.0)

            marker = "P" if item.paraphrased else " "
            top_similarity = results[0].similarity if results else 0.0
            rank_text = str(rank) if rank else "—"
            asked = item.question[:58]
            print(f"{marker:2} {asked:<58} {rank_text:>4} {top_similarity:>6.3f}")

        total = len(QUESTIONS)
        print("-" * len(header))
        print(f"\n  hit@1 : {hits_at_1}/{total}  ({hits_at_1 / total:.0%})")
        print(f"  hit@3 : {hits_at_3}/{total}  ({hits_at_3 / total:.0%})")
        print(f"  MRR   : {sum(reciprocal_ranks) / total:.3f}")
        print("  (P = paraphrased: little vocabulary shared with the source passage)")

        print("\nOut-of-scope questions — nothing should clear the threshold:")
        for question in OUT_OF_SCOPE_QUESTIONS:
            embedding = provider.embed_query(question)
            above = retrieval.search(
                user.id,
                course.id,
                embedding,
                top_k=5,
                min_similarity=settings.RAG_MIN_SIMILARITY,
            )
            best = retrieval.search(user.id, course.id, embedding, top_k=1)
            best_similarity = best[0].similarity if best else 0.0
            verdict = "DECLINES" if not above else f"WOULD ANSWER ({len(above)} chunks)"
            print(f"  {question[:56]:<58} best={best_similarity:>6.3f}  {verdict}")

    Base.metadata.drop_all(engine)
    engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
