"""Background processing: status transitions and chunk persistence.

`TestClient` runs background tasks after the response, so uploading through the API
exercises the real scheduling path rather than calling the processor directly.
"""

import io

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk, ProcessingStatus
from app.services.rag.embeddings import EmbeddingError
from app.tests.conftest import auth
from app.tests.factories import make_image_only_pdf, make_text_pdf


def upload(client: TestClient, token: str, course_id: str, name: str, data: bytes):
    return client.post(
        f"/api/v1/courses/{course_id}/documents",
        files={"file": (name, io.BytesIO(data), "application/octet-stream")},
        headers=auth(token),
    )


def chunks_for(session: Session, document_id: str) -> list[DocumentChunk]:
    return list(
        session.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index)
        )
    )


def test_upload_responds_before_processing(
    client: TestClient, token: str, course_id: str
) -> None:
    """The response is built before the background task runs."""
    response = upload(
        client, token, course_id, "notes.txt", b"Sliding windows control flow."
    )

    assert response.status_code == 201
    assert response.json()["processing_status"] == "uploaded"


def test_successful_processing_reaches_ready(
    client: TestClient, token: str, course_id: str
) -> None:
    document_id = upload(
        client,
        token,
        course_id,
        "notes.txt",
        b"TCP congestion control halves the window.",
    ).json()["id"]

    document = client.get(f"/api/v1/documents/{document_id}", headers=auth(token)).json()

    assert document["processing_status"] == "ready"
    assert document["processing_error"] is None


def test_chunks_are_persisted_with_page_numbers(
    client: TestClient, token: str, course_id: str, session: Session
) -> None:
    document_id = upload(
        client,
        token,
        course_id,
        "lecture.pdf",
        make_text_pdf(
            [
                "TCP halves the congestion window after packet loss.",
                "DNS resolves names into IP addresses.",
            ]
        ),
    ).json()["id"]

    stored = chunks_for(session, document_id)

    assert len(stored) >= 2
    assert [chunk.chunk_index for chunk in stored] == list(range(len(stored)))
    assert {chunk.page_number for chunk in stored} == {1, 2}
    assert all(len(chunk.embedding) == 1536 for chunk in stored)


def test_extraction_failure_marks_the_document_failed(
    client: TestClient, token: str, course_id: str, session: Session
) -> None:
    """A scanned PDF must not be reported as processed."""
    document_id = upload(
        client, token, course_id, "scan.pdf", make_image_only_pdf()
    ).json()["id"]

    document = client.get(f"/api/v1/documents/{document_id}", headers=auth(token)).json()

    assert document["processing_status"] == "failed"
    assert "image-only" in document["processing_error"]
    # A failed document contributes nothing to retrieval.
    assert chunks_for(session, document_id) == []


def test_embedding_failure_marks_the_document_failed(
    client: TestClient, token: str, course_id: str, session: Session
) -> None:
    from app.api.deps import get_embedding_factory
    from app.tests.fakes import FailingEmbeddingProvider

    failing = FailingEmbeddingProvider(
        EmbeddingError("The embedding provider could not be reached.")
    )
    client.app.dependency_overrides[get_embedding_factory] = lambda: lambda: failing

    document_id = upload(
        client, token, course_id, "notes.txt", b"Some readable text here."
    ).json()["id"]

    document = client.get(f"/api/v1/documents/{document_id}", headers=auth(token)).json()

    assert document["processing_status"] == "failed"
    assert document["processing_error"]
    assert chunks_for(session, document_id) == []


def test_processing_errors_never_leak_internals(
    client: TestClient, token: str, course_id: str
) -> None:
    document_id = upload(
        client, token, course_id, "scan.pdf", make_image_only_pdf()
    ).json()["id"]

    message = client.get(f"/api/v1/documents/{document_id}", headers=auth(token)).json()[
        "processing_error"
    ]

    for leak in ("Traceback", "/Users/", "app/services", "Error:"):
        assert leak not in message


def test_reprocessing_a_ready_document_is_skipped(
    client: TestClient, token: str, course_id: str, session: Session, embeddings
) -> None:
    """Re-embedding unchanged content would cost money for an identical result."""
    import uuid as uuid_module

    from app.api.deps import get_session_factory, get_storage
    from app.services.rag import DocumentProcessor

    document_id = upload(
        client, token, course_id, "notes.txt", b"Flow control uses windows."
    ).json()["id"]
    calls_after_upload = len(embeddings.embed_calls)

    processor = DocumentProcessor(
        client.app.dependency_overrides[get_session_factory](),
        client.app.dependency_overrides[get_storage](),
        lambda: embeddings,
    )
    processor.process(uuid_module.UUID(document_id))

    assert len(embeddings.embed_calls) == calls_after_upload


def test_deleting_a_document_removes_its_chunks(
    client: TestClient, token: str, course_id: str, session: Session
) -> None:
    document_id = upload(
        client, token, course_id, "notes.txt", b"Routing tables and paths."
    ).json()["id"]
    assert chunks_for(session, document_id)

    client.delete(f"/api/v1/documents/{document_id}", headers=auth(token))
    session.expire_all()

    assert chunks_for(session, document_id) == []


def test_deleting_a_course_removes_its_chunks(
    client: TestClient, token: str, course_id: str, session: Session
) -> None:
    document_id = upload(
        client, token, course_id, "notes.txt", b"Subnetting and CIDR blocks."
    ).json()["id"]
    assert chunks_for(session, document_id)

    client.delete(f"/api/v1/courses/{course_id}", headers=auth(token))
    session.expire_all()

    assert chunks_for(session, document_id) == []
    assert session.scalar(select(Document).where(Document.id == document_id)) is None


def test_status_progresses_uploaded_then_ready(
    client: TestClient, token: str, course_id: str
) -> None:
    """The two observable ends of the transition, in order."""
    response = upload(
        client, token, course_id, "notes.txt", b"Congestion avoidance and AIMD."
    )
    assert response.json()["processing_status"] == ProcessingStatus.UPLOADED.value

    after = client.get(
        f"/api/v1/documents/{response.json()['id']}", headers=auth(token)
    ).json()
    assert after["processing_status"] == ProcessingStatus.READY.value


def test_reprocess_rebuilds_chunks(
    client: TestClient, token: str, course_id: str, session: Session, embeddings
) -> None:
    """The documented path after an embedding-provider change."""
    document_id = upload(
        client, token, course_id, "notes.txt", b"Congestion control and window sizing."
    ).json()["id"]
    original = {chunk.id for chunk in chunks_for(session, document_id)}
    assert original

    # Simulate the provider-change migration: chunks cleared, status reset.
    session.execute(
        DocumentChunk.__table__.delete().where(DocumentChunk.document_id == document_id)
    )
    document = session.get(Document, document_id)
    assert document is not None
    document.processing_status = ProcessingStatus.UPLOADED
    session.flush()

    response = client.post(
        f"/api/v1/documents/{document_id}/reprocess", headers=auth(token)
    )
    assert response.status_code == 202

    session.expire_all()
    rebuilt = chunks_for(session, document_id)
    assert rebuilt
    # New rows, not the originals.
    assert {chunk.id for chunk in rebuilt}.isdisjoint(original)
    assert session.get(Document, document_id).processing_status is ProcessingStatus.READY


def test_reprocess_forces_work_on_an_already_ready_document(
    client: TestClient, token: str, course_id: str, embeddings
) -> None:
    document_id = upload(
        client, token, course_id, "notes.txt", b"Routing and paths."
    ).json()["id"]
    calls_before = len(embeddings.embed_calls)

    client.post(f"/api/v1/documents/{document_id}/reprocess", headers=auth(token))

    # `force=True` bypasses the "already ready, skip" short-circuit.
    assert len(embeddings.embed_calls) > calls_before


def test_cannot_reprocess_another_users_document(
    client: TestClient, token: str, other_token: str, course_id: str
) -> None:
    document_id = upload(
        client, token, course_id, "notes.txt", b"Private material."
    ).json()["id"]

    response = client.post(
        f"/api/v1/documents/{document_id}/reprocess", headers=auth(other_token)
    )
    assert response.status_code == 404


def test_reprocess_requires_authentication(
    client: TestClient, token: str, course_id: str
) -> None:
    document_id = upload(client, token, course_id, "notes.txt", b"Material.").json()["id"]

    assert client.post(f"/api/v1/documents/{document_id}/reprocess").status_code == 401
