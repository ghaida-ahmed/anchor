"""Document upload, validation, retrieval and ownership isolation."""

import io
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services.storage import LocalStorageService
from app.tests.conftest import auth

MINIMAL_PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


def upload(
    client: TestClient,
    token: str,
    course_id: str,
    filename: str,
    content: bytes,
    content_type: str = "application/octet-stream",
):
    return client.post(
        f"/api/v1/courses/{course_id}/documents",
        files={"file": (filename, io.BytesIO(content), content_type)},
        headers=auth(token),
    )


def test_upload_a_pdf(client: TestClient, token: str, course_id: str) -> None:
    response = upload(client, token, course_id, "Lecture 04.pdf", MINIMAL_PDF)

    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "Lecture 04.pdf"
    assert body["original_filename"] == "Lecture 04.pdf"
    assert body["file_type"] == "pdf"
    assert body["file_size"] == len(MINIMAL_PDF)
    # Nothing has read the file yet — it must not claim otherwise.
    assert body["processing_status"] == "uploaded"


def test_upload_a_text_file(client: TestClient, token: str, course_id: str) -> None:
    response = upload(
        client, token, course_id, "notes.txt", b"lecture notes", "text/plain"
    )

    assert response.status_code == 201
    assert response.json()["file_type"] == "txt"


def test_upload_markdown(client: TestClient, token: str, course_id: str) -> None:
    response = upload(
        client, token, course_id, "summary.md", b"# Heading", "text/markdown"
    )

    assert response.status_code == 201
    assert response.json()["file_type"] == "md"


def test_storage_path_is_never_exposed(
    client: TestClient, token: str, course_id: str
) -> None:
    body = upload(client, token, course_id, "notes.txt", b"x").json()
    assert "storage_path" not in body


def test_file_is_written_to_storage(
    client: TestClient, token: str, course_id: str, storage: LocalStorageService, session
) -> None:
    from sqlalchemy import select

    from app.models import Document

    document_id = upload(client, token, course_id, "notes.txt", b"hello there").json()[
        "id"
    ]

    document = session.scalar(
        select(Document).where(Document.id == uuid.UUID(document_id))
    )
    assert document is not None
    assert storage.exists(document.storage_path)
    assert storage.get_path(document.storage_path).read_bytes() == b"hello there"


def test_stored_filename_is_generated_not_user_supplied(
    client: TestClient, token: str, course_id: str, session
) -> None:
    """A traversal attempt in the filename must not reach the filesystem."""
    from sqlalchemy import select

    from app.models import Document

    response = upload(client, token, course_id, "../../../etc/passwd.txt", b"x")
    assert response.status_code == 201
    assert response.json()["filename"] == "passwd.txt"

    document = session.scalar(
        select(Document).where(Document.id == uuid.UUID(response.json()["id"]))
    )
    assert document is not None
    assert ".." not in document.storage_path
    assert document.storage_path.endswith(".txt")


@pytest.mark.parametrize(
    "filename", ["malware.exe", "slides.pptx", "sheet.xlsx", "noextension"]
)
def test_unsupported_file_types_are_rejected(
    client: TestClient, token: str, course_id: str, filename: str
) -> None:
    response = upload(client, token, course_id, filename, b"content")

    assert response.status_code == 422
    assert "detail" in response.json()


def test_a_renamed_binary_is_not_accepted_as_a_pdf(
    client: TestClient, token: str, course_id: str
) -> None:
    response = upload(client, token, course_id, "fake.pdf", b"MZ\x90\x00 not a pdf")

    assert response.status_code == 422
    assert "not a valid PDF" in response.json()["detail"]


def test_empty_file_is_rejected(client: TestClient, token: str, course_id: str) -> None:
    response = upload(client, token, course_id, "empty.txt", b"")

    assert response.status_code == 422
    assert "empty" in response.json()["detail"].lower()


def test_oversized_file_is_rejected(
    client: TestClient, token: str, course_id: str
) -> None:
    oversized = b"x" * (settings.MAX_UPLOAD_BYTES + 1)
    response = upload(client, token, course_id, "huge.txt", oversized)

    assert response.status_code == 422
    assert "smaller" in response.json()["detail"]


def test_list_documents_for_a_course(
    client: TestClient, token: str, course_id: str
) -> None:
    upload(client, token, course_id, "one.txt", b"a")
    upload(client, token, course_id, "two.txt", b"b")

    response = client.get(f"/api/v1/courses/{course_id}/documents", headers=auth(token))

    assert response.status_code == 200
    assert {item["filename"] for item in response.json()} == {"one.txt", "two.txt"}


def test_course_document_count_reflects_uploads(
    client: TestClient, token: str, course_id: str
) -> None:
    upload(client, token, course_id, "one.txt", b"a")

    course = client.get(f"/api/v1/courses/{course_id}", headers=auth(token)).json()
    assert course["document_count"] == 1


def test_read_one_document(client: TestClient, token: str, course_id: str) -> None:
    document_id = upload(client, token, course_id, "notes.txt", b"x").json()["id"]

    response = client.get(f"/api/v1/documents/{document_id}", headers=auth(token))

    assert response.status_code == 200
    assert response.json()["id"] == document_id


def test_delete_a_document_removes_the_file(
    client: TestClient, token: str, course_id: str, storage: LocalStorageService, session
) -> None:
    from sqlalchemy import select

    from app.models import Document

    document_id = upload(client, token, course_id, "notes.txt", b"x").json()["id"]
    document = session.scalar(
        select(Document).where(Document.id == uuid.UUID(document_id))
    )
    assert document is not None
    key = document.storage_path

    assert (
        client.delete(f"/api/v1/documents/{document_id}", headers=auth(token)).status_code
        == 204
    )
    assert (
        client.get(f"/api/v1/documents/{document_id}", headers=auth(token)).status_code
        == 404
    )
    assert not storage.exists(key)


def test_deleting_a_course_deletes_its_documents(
    client: TestClient, token: str, course_id: str
) -> None:
    document_id = upload(client, token, course_id, "notes.txt", b"x").json()["id"]

    client.delete(f"/api/v1/courses/{course_id}", headers=auth(token))

    assert (
        client.get(f"/api/v1/documents/{document_id}", headers=auth(token)).status_code
        == 404
    )


def test_document_endpoints_require_authentication(
    client: TestClient, token: str, course_id: str
) -> None:
    document_id = upload(client, token, course_id, "notes.txt", b"x").json()["id"]

    assert client.get(f"/api/v1/courses/{course_id}/documents").status_code == 401
    assert client.get(f"/api/v1/documents/{document_id}").status_code == 401
    assert client.delete(f"/api/v1/documents/{document_id}").status_code == 401


def test_cannot_upload_to_another_users_course(
    client: TestClient, other_token: str, course_id: str
) -> None:
    response = upload(client, other_token, course_id, "notes.txt", b"x")
    assert response.status_code == 404


def test_cannot_list_another_users_documents(
    client: TestClient, other_token: str, course_id: str
) -> None:
    response = client.get(
        f"/api/v1/courses/{course_id}/documents", headers=auth(other_token)
    )
    assert response.status_code == 404


def test_cannot_read_or_delete_another_users_document(
    client: TestClient, token: str, other_token: str, course_id: str
) -> None:
    document_id = upload(client, token, course_id, "notes.txt", b"x").json()["id"]

    assert (
        client.get(
            f"/api/v1/documents/{document_id}", headers=auth(other_token)
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/documents/{document_id}", headers=auth(other_token)
        ).status_code
        == 404
    )
    # Still there for its real owner.
    assert (
        client.get(f"/api/v1/documents/{document_id}", headers=auth(token)).status_code
        == 200
    )
