"""Both storage backends, against the one interface the application uses.

No Supabase credentials are needed: the HTTP client is injected, so these run
offline in CI exactly as they do locally. What they pin down is the contract —
if a backend can be swapped by configuration alone, the two must agree on what
every method does, including how each one fails.
"""

import io
import uuid
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.exceptions import ResourceNotFoundError, StorageError
from app.services.storage import (
    LocalStorageService,
    StorageService,
    SupabaseStorageService,
    build_storage_key,
    get_storage_service,
)

BUCKET = "course-documents"
BASE_URL = "https://project.supabase.co"


class FakeResponse:
    def __init__(self, status_code: int, content: bytes = b"") -> None:
        self.status_code = status_code
        self.content = content


class FakeHttpClient:
    """Records requests and returns scripted responses.

    Deliberately not a mock library: asserting on a recorded list keeps the tests
    readable, and the request log is what proves the service role key is sent as a
    header rather than, say, a query parameter that would land in an access log.
    """

    def __init__(self, **scripted: FakeResponse) -> None:
        self.scripted = scripted
        self.requests: list[tuple[str, str]] = []
        self.raise_on: set[str] = set()

    def _respond(self, method: str, url: str) -> FakeResponse:
        self.requests.append((method, url))
        if method in self.raise_on:
            raise ConnectionError("simulated transport failure")
        return self.scripted.get(method, FakeResponse(200))

    def post(self, url, content=None, headers=None):
        self.last_body = content
        return self._respond("post", url)

    def get(self, url):
        return self._respond("get", url)

    def head(self, url):
        return self._respond("head", url)

    def delete(self, url):
        return self._respond("delete", url)


@pytest.fixture
def supabase_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "SUPABASE_URL", BASE_URL)
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "service-role-test-value")
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_BUCKET", BUCKET)


def supabase(client: FakeHttpClient) -> SupabaseStorageService:
    return SupabaseStorageService(client=client)


class TestKeys:
    def test_a_key_never_contains_the_users_filename(self) -> None:
        key = build_storage_key(uuid.uuid4(), "pdf")
        assert key.endswith(".pdf")
        assert ".." not in key
        # course-id / random-hex . ext
        course, name = key.split("/")
        uuid.UUID(course)  # raises if it is not a real id
        assert len(name.split(".")[0]) == 32

    def test_the_extension_is_normalised(self) -> None:
        assert build_storage_key(uuid.uuid4(), ".PDF").endswith(".pdf")


class TestLocalUnchanged:
    """The development and test backend must behave exactly as it did before."""

    def test_round_trip(self, tmp_path: Path) -> None:
        storage = LocalStorageService(root=tmp_path)
        storage.save("course/file.txt", io.BytesIO(b"hello there"))

        assert storage.exists("course/file.txt")
        with storage.open("course/file.txt") as stream:
            assert stream.read() == b"hello there"

        storage.delete("course/file.txt")
        assert not storage.exists("course/file.txt")

    def test_delete_is_idempotent(self, tmp_path: Path) -> None:
        LocalStorageService(root=tmp_path).delete("never/existed.txt")

    def test_local_path_yields_the_real_file_and_does_not_remove_it(
        self, tmp_path: Path
    ) -> None:
        storage = LocalStorageService(root=tmp_path)
        storage.save("course/file.txt", io.BytesIO(b"content"))

        with storage.local_path("course/file.txt") as path:
            assert path.read_bytes() == b"content"
            kept = path

        # Local storage owns the file; the context manager must not delete it.
        assert kept.is_file()

    def test_opening_a_missing_file_is_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(ResourceNotFoundError):
            LocalStorageService(root=tmp_path).open("course/gone.txt")

    def test_traversal_is_refused(self, tmp_path: Path) -> None:
        storage = LocalStorageService(root=tmp_path)
        for key in ("../escaped.txt", "/etc/passwd", "a/../../b.txt"):
            with pytest.raises(StorageError):
                storage.save(key, io.BytesIO(b"nope"))


class TestSupabaseUpload:
    def test_a_successful_upload_posts_the_bytes_to_the_bucket(
        self, supabase_configured
    ) -> None:
        client = FakeHttpClient(post=FakeResponse(200))
        supabase(client).save("course/doc.pdf", io.BytesIO(b"%PDF-1.4"))

        method, url = client.requests[0]
        assert method == "post"
        assert url == f"{BASE_URL}/storage/v1/object/{BUCKET}/course/doc.pdf"
        assert client.last_body == b"%PDF-1.4"

    def test_a_rejected_upload_raises_storage_error(self, supabase_configured) -> None:
        client = FakeHttpClient(post=FakeResponse(403, b"forbidden: bucket policy"))
        with pytest.raises(StorageError):
            supabase(client).save("course/doc.pdf", io.BytesIO(b"data"))

    def test_the_provider_body_is_not_leaked_into_the_error(
        self, supabase_configured
    ) -> None:
        """A provider error body can echo the request, and the request is the
        student's file."""
        client = FakeHttpClient(post=FakeResponse(400, b"echo of the uploaded bytes"))
        with pytest.raises(StorageError) as caught:
            supabase(client).save("course/doc.pdf", io.BytesIO(b"data"))
        assert "echo of the uploaded bytes" not in str(caught.value)

    def test_a_transport_failure_raises_storage_error(self, supabase_configured) -> None:
        client = FakeHttpClient()
        client.raise_on.add("post")
        with pytest.raises(StorageError):
            supabase(client).save("course/doc.pdf", io.BytesIO(b"data"))


class TestSupabaseDownload:
    def test_open_returns_the_object_bytes(self, supabase_configured) -> None:
        client = FakeHttpClient(get=FakeResponse(200, b"%PDF-1.4 body"))
        with supabase(client).open("course/doc.pdf") as stream:
            assert stream.read() == b"%PDF-1.4 body"

    def test_a_missing_object_is_not_found_not_an_error(
        self, supabase_configured
    ) -> None:
        """So a deleted file and a foreign document look identical to a client."""
        client = FakeHttpClient(get=FakeResponse(404))
        with pytest.raises(ResourceNotFoundError):
            supabase(client).open("course/gone.pdf")

    def test_a_provider_failure_raises_storage_error(self, supabase_configured) -> None:
        client = FakeHttpClient(get=FakeResponse(500))
        with pytest.raises(StorageError):
            supabase(client).open("course/doc.pdf")

    def test_local_path_downloads_then_removes_the_temp_file(
        self, supabase_configured
    ) -> None:
        client = FakeHttpClient(get=FakeResponse(200, b"extractable text"))
        storage = supabase(client)

        with storage.local_path("course/doc.txt") as path:
            assert path.read_bytes() == b"extractable text"
            assert path.suffix == ".txt"
            temp = path

        assert not temp.exists(), "the downloaded copy must not outlive the block"

    def test_the_temp_file_is_removed_even_when_the_block_raises(
        self, supabase_configured
    ) -> None:
        """Extraction failures are routine — a corrupt PDF — and must not leave a
        copy of a student's document behind."""
        client = FakeHttpClient(get=FakeResponse(200, b"data"))
        storage = supabase(client)

        temp = None
        with (
            pytest.raises(RuntimeError),
            storage.local_path("course/doc.pdf") as path,
        ):
            temp = path
            raise RuntimeError("extraction blew up")

        assert temp is not None and not temp.exists()


class TestSupabaseDeleteAndExists:
    def test_delete_calls_the_object_endpoint(self, supabase_configured) -> None:
        client = FakeHttpClient(delete=FakeResponse(200))
        supabase(client).delete("course/doc.pdf")
        assert client.requests[0][0] == "delete"

    def test_deleting_a_missing_object_succeeds(self, supabase_configured) -> None:
        """`delete` promises idempotence, so 404 is success."""
        client = FakeHttpClient(delete=FakeResponse(404))
        supabase(client).delete("course/gone.pdf")

    def test_a_failed_delete_raises(self, supabase_configured) -> None:
        client = FakeHttpClient(delete=FakeResponse(500))
        with pytest.raises(StorageError):
            supabase(client).delete("course/doc.pdf")

    def test_exists_is_true_for_a_present_object(self, supabase_configured) -> None:
        assert supabase(FakeHttpClient(head=FakeResponse(200))).exists("course/doc.pdf")

    def test_exists_is_false_for_a_missing_object(self, supabase_configured) -> None:
        assert not supabase(FakeHttpClient(head=FakeResponse(404))).exists("course/x.pdf")

    def test_a_transport_blip_reports_absent_rather_than_raising(
        self, supabase_configured
    ) -> None:
        """Every caller of `exists` already handles a missing file; a 500 on a
        network blip would be worse than a 404."""
        client = FakeHttpClient()
        client.raise_on.add("head")
        assert not supabase(client).exists("course/doc.pdf")


class TestSupabaseSafety:
    def test_traversal_keys_are_refused_before_any_request(
        self, supabase_configured
    ) -> None:
        """The key becomes a URL path, so `..` must never reach the provider."""
        client = FakeHttpClient()
        storage = supabase(client)
        for key in ("../other-bucket/file.pdf", "/absolute.pdf", "a/../../b.pdf"):
            with pytest.raises(StorageError):
                storage.open(key)
        assert client.requests == [], "no request should have been attempted"

    def test_the_service_role_key_is_sent_as_a_header_not_in_the_url(
        self, supabase_configured
    ) -> None:
        """A key in a query string lands in every proxy and access log between
        here and the provider."""
        client = FakeHttpClient(get=FakeResponse(200, b"x"))
        supabase(client).open("course/doc.pdf")
        _, url = client.requests[0]
        assert "service-role-test-value" not in url

    def test_no_public_or_signed_url_is_ever_produced(self) -> None:
        """Bytes are streamed through FastAPI so the ownership check stays the
        only way in. If a `sign` call appears here, that guarantee has changed."""
        source = Path("app/services/storage.py").read_text()
        assert "/object/sign/" not in source
        assert "createSignedUrl" not in source
        assert "/object/public/" not in source


class TestConfiguration:
    def test_selecting_supabase_without_configuring_it_fails_by_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "SUPABASE_URL", None)
        monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", None)

        with pytest.raises(StorageError) as caught:
            SupabaseStorageService()

        message = str(caught.value)
        assert "SUPABASE_URL" in message
        assert "SUPABASE_SERVICE_ROLE_KEY" in message

    def test_the_configuration_error_names_variables_not_values(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """This message reaches logs."""
        monkeypatch.setattr(settings, "SUPABASE_URL", BASE_URL)
        monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", None)
        monkeypatch.setattr(settings, "SUPABASE_STORAGE_BUCKET", BUCKET)

        with pytest.raises(StorageError) as caught:
            SupabaseStorageService()
        assert BASE_URL not in str(caught.value)

    def test_the_factory_defaults_to_local(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "STORAGE_BACKEND", "local")
        assert isinstance(get_storage_service(), LocalStorageService)

    def test_the_factory_builds_supabase_when_selected(
        self, supabase_configured, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "STORAGE_BACKEND", "supabase")
        assert isinstance(get_storage_service(), SupabaseStorageService)

    def test_an_unknown_backend_fails_loudly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Rather than silently falling back to a backend that loses data."""
        monkeypatch.setattr(settings, "STORAGE_BACKEND", "s3-someday")
        with pytest.raises(ValueError, match="Unknown STORAGE_BACKEND"):
            get_storage_service()


class TestBothBackendsImplementTheInterface:
    def test_neither_backend_is_abstract(self) -> None:
        """A missing method would only surface at runtime, on the one route that
        calls it, in production."""
        for backend in (LocalStorageService, SupabaseStorageService):
            missing = getattr(backend, "__abstractmethods__", frozenset())
            assert not missing, f"{backend.__name__} is missing {sorted(missing)}"

    def test_the_interface_is_exactly_what_callers_use(self) -> None:
        required = {"save", "delete", "exists", "open", "local_path"}
        assert required <= set(StorageService.__abstractmethods__) | {
            name for name in dir(StorageService) if not name.startswith("_")
        }
