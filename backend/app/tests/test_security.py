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
            # A real pooler credential must still be caught, even though the
            # placeholder form of the same URL is allowed above.
            "postgresql+psycopg://"
            + "postgres.abcdef:Xy9RealPass@aws-0-eu-west-1.pooler.supabase.com"
            ":6543/postgres",
            # A password merely *starting* with a placeholder word is not one.
            # The host must also be non-placeholder, or the example-domain rule
            # would excuse this line for a different reason than the one tested.
            "postgresql://" + "postgres:PASSWORDISH123abc@db.acme-corp.io/db",
        ]
        must_pass = [
            "postgresql+psycopg://anchor:anchor@localhost:5432/anchor",
            "DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME",
            "postgresql+psycopg://user:pw@db.example.com:5432/anchor",
            "ordinary prose about document processing",
            # Documentation templates from docs/deployment.md.
            "postgresql://postgres.<project-ref>:[YOUR-PASSWORD]@aws-0-<region>"
            ".pooler.supabase.com:6543/postgres",
            "postgresql+psycopg://postgres:YOUR-PASSWORD@db.<project-ref>"
            ".supabase.co:5432/postgres",
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


class TestAuthenticationStaysAnchorsOwn:
    """Supabase hosts the database and the file bucket. It does NOT do auth.

    Adding a Supabase dependency is exactly the moment someone might reach for
    Supabase Auth, so the boundary is pinned here rather than left to reviewer
    memory. Registration and login stay: React -> FastAPI -> bcrypt/JWT ->
    `users` table over SQLAlchemy.
    """

    def test_registration_writes_to_the_users_table(self, client: TestClient, session):
        from app.models import User

        email = unique_email("ownauth")
        response = client.post(
            "/api/v1/auth/register",
            json={"name": "Own Auth", "email": email, "password": "correct-horse-9"},
        )
        assert response.status_code == 201

        row = session.query(User).filter(User.email == email).one()
        assert row.hashed_password
        # Never the plaintext, and a bcrypt hash by shape.
        assert row.hashed_password != "correct-horse-9"
        assert row.hashed_password.startswith("$2")

    def test_login_verifies_against_that_hash(self, client: TestClient):
        email = unique_email("ownauth-login")
        client.post(
            "/api/v1/auth/register",
            json={"name": "Own Auth", "email": email, "password": "correct-horse-9"},
        )
        good = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "correct-horse-9"},
        )
        bad = client.post(
            "/api/v1/auth/login", json={"email": email, "password": "wrong-password"}
        )
        assert good.status_code == 200 and good.json()["access_token"]
        assert bad.status_code == 401

    def test_the_token_is_signed_and_verified_by_anchor(self, client: TestClient):
        """Decoded with ANCHOR's own key, so no external issuer is involved."""
        import jwt

        email = unique_email("ownauth-jwt")
        token = client.post(
            "/api/v1/auth/register",
            json={"name": "Own Auth", "email": email, "password": "correct-horse-9"},
        ).json()["access_token"]

        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        assert uuid.UUID(payload["sub"])
        assert "exp" in payload

    def test_no_supabase_auth_anywhere_in_the_backend(self):
        """Supabase appears only in the storage backend and its configuration."""
        import pathlib

        # Assembled at runtime: written as literals they would match this very
        # file, and a check that trips on itself gets deleted rather than fixed.
        forbidden = ["supabase" + ".auth", "go" + "true", "sign_in_" + "with"]

        offenders = []
        for path in pathlib.Path("app").rglob("*.py"):
            # This file necessarily contains the strings it searches for.
            if path.name == "test_security.py":
                continue
            text = path.read_text()
            lowered = text.lower()
            if "supabase" in lowered:
                # storage.py — the backend itself
                # config.py  — its settings
                # session.py — names the pooler host for prepared-statement
                #              compatibility; nothing to do with auth
                allowed = (
                    path.name in {"storage.py", "config.py", "session.py"}
                    or "tests" in path.parts
                )
                if not allowed:
                    offenders.append(str(path))
            for needle in forbidden:
                assert needle not in lowered, f"{path}: {needle}"

        assert not offenders, f"Supabase referenced outside storage/config: {offenders}"

    def test_the_supabase_client_library_is_not_a_dependency(self):
        """Storage talks to a documented REST endpoint with httpx. Pulling in the
        SDK would add the Postgres and Auth surface ANCHOR deliberately avoids."""
        import pathlib

        requirements = pathlib.Path("requirements.txt").read_text()
        # Package names only — comments legitimately mention Supabase.
        packages = [
            line.split("==")[0].split("[")[0].strip().lower()
            for line in requirements.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        assert "supabase" not in packages
        assert "gotrue" not in packages
        assert "storage3" not in packages
        # And the client we DO use is declared rather than relied on transitively.
        assert "httpx" in packages
