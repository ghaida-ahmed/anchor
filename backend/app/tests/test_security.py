"""Security properties that must hold before this repository is public.

Several of these duplicate coverage in the feature suites, deliberately. A
security guarantee should fail loudly in a file named after it, not quietly
inside a test about quiz generation that someone later rewrites.
"""

import io
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import MAX_PASSWORD_BYTES, create_access_token
from app.services.storage import LocalStorageService, build_storage_key
from app.tests.conftest import auth, unique_email

REPO_ROOT = Path(__file__).resolve().parents[3]
PDF = b"%PDF-1.4\n% minimal\n"


class TestSecretsAreNotCommittable:
    """The repository is about to be published. These are the last line."""

    def test_the_scanner_finds_nothing_in_tracked_files(self) -> None:
        script = REPO_ROOT / "scripts" / "scan_secrets.py"
        assert script.exists(), "scripts/scan_secrets.py is missing"

        result = subprocess.run(
            ["python3", str(script)], cwd=REPO_ROOT, capture_output=True, text=True
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_the_scanner_still_catches_a_real_credential(self) -> None:
        """The allowlist is the scanner's weak point — every entry is a hole.

        A scanner that only ever passes is indistinguishable from no scanner, so
        this pins both directions: obvious placeholders are ignored, and anything
        pointing at a host that could exist is still a finding.
        """
        import importlib.util

        script = REPO_ROOT / "scripts" / "scan_secrets.py"
        spec = importlib.util.spec_from_file_location("scan_secrets", script)
        scanner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scanner)

        def flagged(line: str) -> bool:
            if any(allowed.search(line) for allowed in scanner.ALLOWED):
                return False
            return any(p.search(line) for p in scanner.PATTERNS.values())

        # Assembled at runtime rather than written as literals. These are fake,
        # but a scanner that skipped the file containing them would be a real
        # hole — somewhere a genuine key could be hidden. Splitting each string
        # means the pattern never appears in the source, so the scanner keeps
        # covering this file like any other.
        must_flag = [
            "postgresql://" + "admin:hunter2@db.production.internal:5432/anchor",
            "postgres://" + "root:S3cret@10.0.0.5/main",
            "AIza" + "SyD1234567890abcdefghijklmnopqrstuvw",
            "sk-" + "proj-abcdefghijklmnopqrstuvwxyz0123456789",
            "ghp" + "_abcdefghijklmnopqrstuvwxyz0123456789AB",
            "-----BEGIN " + "RSA PRIVATE KEY-----",
        ]
        must_pass = [
            "postgresql+psycopg://anchor:anchor@localhost:5432/anchor",
            "DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME",
            "postgresql+psycopg://user:pw@db.example.com:5432/anchor",
            "ordinary prose about document processing",
        ]

        for line in must_flag:
            assert flagged(line), f"scanner missed: {line[:40]}"
        for line in must_pass:
            assert not flagged(line), f"false positive: {line[:40]}"

    def test_backend_env_is_ignored_by_git(self) -> None:
        """The one file holding real keys must never become trackable."""
        result = subprocess.run(
            ["git", "check-ignore", "backend/.env"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, "backend/.env is NOT gitignored"

    def test_uploaded_documents_are_ignored_by_git(self) -> None:
        result = subprocess.run(
            ["git", "check-ignore", "backend/storage/documents/example.pdf"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, "uploaded documents are NOT gitignored"

    def test_env_examples_carry_no_real_values(self) -> None:
        for name in (".env.example", "backend/.env.example", "frontend/.env.example"):
            path = REPO_ROOT / name
            if not path.exists():
                continue
            for line in path.read_text().splitlines():
                for key in ("GEMINI_API_KEY", "OPENAI_API_KEY", "SECRET_KEY"):
                    if line.startswith(f"{key}="):
                        value = line.split("=", 1)[1].strip()
                        assert value == "", f"{name}: {key} has a non-empty value"


class TestTokenHandling:
    def test_a_token_signed_with_another_key_is_rejected(
        self, client: TestClient
    ) -> None:
        forged = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "exp": datetime.now(UTC) + timedelta(hours=1),
            },
            "an-attacker-chosen-signing-key",
            algorithm="HS256",
        )
        response = client.get("/api/v1/auth/me", headers=auth(forged))
        assert response.status_code == 401

    def test_an_expired_token_is_rejected(self, client: TestClient) -> None:
        expired = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "iat": datetime.now(UTC) - timedelta(hours=2),
                "exp": datetime.now(UTC) - timedelta(hours=1),
            },
            settings.SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )
        assert client.get("/api/v1/auth/me", headers=auth(expired)).status_code == 401

    def test_an_alg_none_token_is_rejected(self, client: TestClient) -> None:
        """`decode` pins `algorithms=[...]`, so an unsigned token cannot pass."""
        unsigned = jwt.encode({"sub": str(uuid.uuid4())}, key="", algorithm="none")
        assert client.get("/api/v1/auth/me", headers=auth(unsigned)).status_code == 401

    def test_a_token_for_a_deleted_user_is_rejected(self, client: TestClient) -> None:
        """A valid signature for a subject that no longer exists."""
        token = create_access_token(uuid.uuid4())
        assert client.get("/api/v1/auth/me", headers=auth(token)).status_code == 401

    def test_garbage_and_missing_tokens_are_rejected(self, client: TestClient) -> None:
        assert client.get("/api/v1/auth/me").status_code == 401
        assert (
            client.get("/api/v1/auth/me", headers=auth("not.a.token")).status_code == 401
        )
        assert (
            client.get("/api/v1/auth/me", headers={"Authorization": "Bearer"}).status_code
            == 401
        )

    def test_an_overlong_password_is_refused_not_truncated(
        self, client: TestClient
    ) -> None:
        """bcrypt silently truncates at 72 bytes, which would make two different
        long passwords interchangeable."""
        response = client.post(
            "/api/v1/auth/register",
            json={
                "name": "Long",
                "email": unique_email("long"),
                "password": "a" * (MAX_PASSWORD_BYTES + 10),
            },
        )
        assert response.status_code == 422


class TestUploadSecurity:
    def test_an_executable_is_refused(self, client: TestClient, token, course_id) -> None:
        response = client.post(
            f"/api/v1/courses/{course_id}/documents",
            files={
                "file": (
                    "payload.sh",
                    io.BytesIO(b"#!/bin/sh\nrm -rf /"),
                    "application/x-sh",
                )
            },
            headers=auth(token),
        )
        assert response.status_code == 422

    def test_a_pdf_extension_without_pdf_content_is_refused(
        self, client: TestClient, token, course_id
    ) -> None:
        """The browser-supplied type is not trusted; the magic bytes are checked."""
        response = client.post(
            f"/api/v1/courses/{course_id}/documents",
            files={
                "file": ("fake.pdf", io.BytesIO(b"not a pdf at all"), "application/pdf")
            },
            headers=auth(token),
        )
        assert response.status_code == 422

    def test_an_oversized_file_is_refused(
        self, client: TestClient, token, course_id, monkeypatch
    ) -> None:
        monkeypatch.setattr(settings, "MAX_UPLOAD_BYTES", 1024)
        response = client.post(
            f"/api/v1/courses/{course_id}/documents",
            files={"file": ("big.txt", io.BytesIO(b"x" * 4096), "text/plain")},
            headers=auth(token),
        )
        assert response.status_code == 422

    def test_an_empty_file_is_refused(self, client: TestClient, token, course_id) -> None:
        response = client.post(
            f"/api/v1/courses/{course_id}/documents",
            files={"file": ("empty.txt", io.BytesIO(b""), "text/plain")},
            headers=auth(token),
        )
        assert response.status_code == 422

    def test_a_traversal_filename_cannot_escape_storage(
        self, client: TestClient, token, course_id, session
    ) -> None:
        """The original name is recorded but never used as a path."""
        response = client.post(
            f"/api/v1/courses/{course_id}/documents",
            files={
                "file": (
                    "../../../../etc/passwd.txt",
                    io.BytesIO(b"content here"),
                    "text/plain",
                )
            },
            headers=auth(token),
        )
        assert response.status_code == 201
        from app.models import Document

        document = session.get(Document, uuid.UUID(response.json()["id"]))
        assert ".." not in document.storage_path
        assert not Path(document.storage_path).is_absolute()

    def test_storage_keys_never_contain_the_users_filename(self) -> None:
        key = build_storage_key(uuid.uuid4(), "pdf")
        assert ".." not in key
        assert key.endswith(".pdf")

    def test_a_traversal_key_is_refused_by_the_backend(self, tmp_path) -> None:
        """Defence in depth: a traversal bug elsewhere must not become an
        arbitrary-file-write bug here."""
        from app.core.exceptions import StorageError

        storage = LocalStorageService(root=tmp_path)
        with pytest.raises(StorageError):
            storage.save("../../escaped.txt", io.BytesIO(b"nope"))


class TestOwnershipIsolation:
    def _upload(self, client, token, course_id, name="notes.txt"):
        response = client.post(
            f"/api/v1/courses/{course_id}/documents",
            files={"file": (name, io.BytesIO(b"Private course material."), "text/plain")},
            headers=auth(token),
        )
        assert response.status_code == 201
        return response.json()["id"]

    def test_another_user_cannot_read_document_metadata(
        self, client: TestClient, token, other_token, course_id
    ) -> None:
        document_id = self._upload(client, token, course_id)
        response = client.get(
            f"/api/v1/documents/{document_id}", headers=auth(other_token)
        )
        assert response.status_code == 404

    def test_another_user_cannot_download_the_file(
        self, client: TestClient, token, other_token, course_id
    ) -> None:
        """The one route that returns raw private material."""
        document_id = self._upload(client, token, course_id)
        response = client.get(
            f"/api/v1/documents/{document_id}/download", headers=auth(other_token)
        )
        assert response.status_code == 404

    def test_an_anonymous_download_is_refused(
        self, client: TestClient, token, course_id
    ) -> None:
        document_id = self._upload(client, token, course_id)
        assert client.get(f"/api/v1/documents/{document_id}/download").status_code == 401

    def test_another_user_cannot_delete_the_document(
        self, client: TestClient, token, other_token, course_id
    ) -> None:
        document_id = self._upload(client, token, course_id)
        assert (
            client.delete(
                f"/api/v1/documents/{document_id}", headers=auth(other_token)
            ).status_code
            == 404
        )

    def test_a_404_is_returned_rather_than_a_403(
        self, client: TestClient, token, other_token, course_id
    ) -> None:
        """403 would confirm the resource exists, which is itself a disclosure."""
        response = client.get(f"/api/v1/courses/{course_id}", headers=auth(other_token))
        assert response.status_code == 404


class TestErrorSanitisation:
    def test_a_provider_failure_is_not_leaked_to_the_client(
        self, client: TestClient, token, course_id, llm
    ) -> None:
        """A raw provider exception can carry the prompt, and the prompt carries
        the student's material."""
        from app.services.rag.generation import GenerationError

        def explode(*_args, **_kwargs):
            raise GenerationError(
                "upstream 500 for key AIzaSyD-secret and prompt 'private notes'"
            )

        llm.generate_json = explode
        response = client.post(
            f"/api/v1/courses/{course_id}/topics/extract", headers=auth(token)
        )
        body = response.text
        assert "AIzaSyD-secret" not in body
        assert "private notes" not in body

    def test_a_database_error_is_replaced_with_a_generic_message(
        self, client: TestClient, token
    ) -> None:
        """Driver text leaks schema details and the connection string."""
        from app.core.exceptions import register_exception_handlers  # noqa: F401

        response = client.get("/api/v1/courses/not-a-uuid", headers=auth(token))
        assert response.status_code in (404, 422)
        assert "psycopg" not in response.text
        assert "postgresql://" not in response.text

    def test_no_response_contains_the_signing_key(
        self, client: TestClient, token, course_id
    ) -> None:
        for path in (
            "/api/health",
            "/api/ready",
            "/api/v1/auth/me",
            f"/api/v1/courses/{course_id}",
        ):
            body = client.get(path, headers=auth(token)).text
            assert settings.SECRET_KEY not in body


class TestReadiness:
    def test_readiness_reports_the_database_and_config(self, client: TestClient) -> None:
        response = client.get("/api/ready")
        assert response.status_code == 200
        body = response.json()
        assert body["database"] is True
        assert body["status"] == "ready"
        assert isinstance(body["ai_provider_configured"], bool)

    def test_readiness_never_returns_the_api_key(self, client: TestClient) -> None:
        body = client.get("/api/ready").text
        if settings.GEMINI_API_KEY:
            assert settings.GEMINI_API_KEY not in body

    def test_liveness_does_not_touch_the_database(self, client: TestClient) -> None:
        """It must keep answering when Postgres is down, or the platform restarts
        a healthy container for a downstream failure."""
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
