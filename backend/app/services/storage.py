"""Storage abstraction for uploaded documents.

Route handlers and `DocumentService` depend on the `StorageService` interface,
never on the filesystem. Selecting a backend is `STORAGE_BACKEND` and nothing else:
no route, service or test above this module knows what a storage key resolves to.

THE INTERFACE, AND WHY IT LOOKS LIKE THIS
=========================================

An earlier version exposed `get_path(key) -> Path`, which quietly assumed every
backend has a filesystem. An object store does not, so the two readers are split
by what they actually need:

    open(key)        a readable stream — used to serve a download
    local_path(key)  a context manager yielding a real path, for code that
                     genuinely needs one

Only text extraction needs the second, because `pypdf` and `Path.read_text` take a
path. The local backend hands back the real file and touches nothing; the Supabase
backend downloads to a temp file and deletes it on exit. Making that a context
manager is what keeps the cleanup impossible to forget.

PRIVACY
=======

Course materials are private. Neither backend ever produces a public URL, and the
Supabase bucket is private: bytes are streamed *through* FastAPI, so the existing
ownership check on the download route stays the only way in. That is a deliberate
choice over signed URLs — a signed URL is a bearer credential that outlives the
request and cannot be un-issued.
"""

import shutil
import tempfile
import uuid
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from app.core.config import settings
from app.core.exceptions import ResourceNotFoundError, StorageError
from app.core.logging import get_logger

logger = get_logger(__name__)

# Resolves relative UPLOAD_DIR values against the backend package root, so the
# location does not depend on the process's working directory.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def build_storage_key(course_id: uuid.UUID, extension: str) -> str:
    """A generated key — the user's filename never touches the filesystem.

    Original names can contain path separators, `..`, control characters or names
    that collide; only the extension is carried over, and it comes from a
    validated allow-list rather than from the upload.

    The course id is a path segment so objects group per course, which makes a
    bucket browsable during debugging. It is a UUID, so it identifies a row and
    reveals nothing about the student — no email, no filename, no title.
    """
    return f"{course_id}/{uuid.uuid4().hex}.{extension.lower().lstrip('.')}"


def _reject_traversal(key: str) -> str:
    """Refuse a key that could escape its prefix.

    Keys come from `build_storage_key`, so this is defence in depth: a traversal
    bug elsewhere must not become an arbitrary-object-write bug. Applied by both
    backends, because Supabase's REST API takes the key as a URL path.
    """
    if not key or key.startswith("/") or ".." in key.split("/") or "\\" in key:
        raise StorageError("Refusing to access a path outside the storage root.")
    return key


class StorageService(ABC):
    """The interface document code is written against."""

    @abstractmethod
    def save(self, key: str, source: BinaryIO) -> None:
        """Persist `source` under `key`, replacing anything already there."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove `key`. Succeeds silently when it is already gone."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Whether `key` is present in the backend."""

    @abstractmethod
    def open(self, key: str) -> BinaryIO:
        """A readable stream of `key`'s bytes.

        Raises `ResourceNotFoundError` when the object is gone — the caller turns
        that into the same 404 a missing document row would produce, so a deleted
        file and a foreign document are indistinguishable to a client.
        """

    @abstractmethod
    @contextmanager
    def local_path(self, key: str) -> Iterator[Path]:
        """Yield a real filesystem path for `key`, for the duration of the block.

        For backends without a filesystem this downloads to a temporary file and
        removes it on exit. Only text extraction should need this.
        """


class LocalStorageService(StorageService):
    """Filesystem-backed storage.

    The development and test backend, and a correct production backend on a host
    with a persistent volume attached.
    """

    def __init__(self, root: Path | None = None) -> None:
        configured = Path(settings.UPLOAD_DIR)
        base = root or (
            configured if configured.is_absolute() else _BACKEND_ROOT / configured
        )
        self.root = base
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        """Resolve `key` under the root, refusing anything that escapes it."""
        _reject_traversal(key)
        candidate = (self.root / key).resolve()
        if not candidate.is_relative_to(self.root.resolve()):
            raise StorageError("Refusing to access a path outside the storage root.")
        return candidate

    def save(self, key: str, source: BinaryIO) -> None:
        destination = self._resolve(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with destination.open("wb") as target:
                shutil.copyfileobj(source, target)
        except OSError as error:
            raise StorageError() from error

    def delete(self, key: str) -> None:
        try:
            self._resolve(key).unlink(missing_ok=True)
        except OSError as error:
            raise StorageError("The file could not be removed.") from error

    def exists(self, key: str) -> bool:
        return self._resolve(key).is_file()

    def open(self, key: str) -> BinaryIO:
        path = self._resolve(key)
        try:
            return path.open("rb")
        except FileNotFoundError as error:
            raise ResourceNotFoundError("Document file", key) from error
        except OSError as error:
            raise StorageError("The file could not be read.") from error

    @contextmanager
    def local_path(self, key: str) -> Iterator[Path]:
        """No copy: the file is already on disk."""
        yield self._resolve(key)

    def get_path(self, key: str) -> Path:
        """The resolved path. Local-only convenience, not part of the interface —
        code that must work on every backend uses `local_path`."""
        return self._resolve(key)


class SupabaseStorageService(StorageService):
    """Supabase Storage, over its S3-style REST API.

    NO SUPABASE CLIENT LIBRARY. The four operations here are plain authenticated
    HTTP against documented endpoints, and `httpx` is already in the dependency
    tree. Adding a vendor SDK for this would pull in a client whose main feature —
    the Postgres and Auth surface — ANCHOR deliberately does not use: the database
    is reached through SQLAlchemy and authentication is ANCHOR's own.

    The bucket MUST be private. Requests authenticate with the project's
    privileged key, which is why it never leaves the backend: it bypasses
    row-level security and can read every object in the project.

    KEY FORMAT IS NOT THIS CLASS'S BUSINESS. Supabase's current dashboard issues
    opaque secret keys (`sb_secret_...`) in place of the legacy `service_role`
    JWT. Both are used the same way — a bearer credential in the Authorization
    and apikey headers — so the value is forwarded verbatim and never parsed.
    That is what makes the key rotation a configuration change rather than a code
    change. `settings.supabase_key` resolves whichever variable is set.

    The Data API (PostgREST, /rest/v1/) can stay disabled: Storage is a separate
    service on /storage/v1/ and does not depend on it.
    """

    # Long enough for a 25 MB upload on a slow connection, short enough that a
    # hung request cannot hold a worker indefinitely.
    TIMEOUT_SECONDS = 60.0

    def __init__(self, client=None) -> None:
        missing = [
            name
            for name, value in (
                ("SUPABASE_URL", settings.SUPABASE_URL),
                ("SUPABASE_SECRET_KEY", settings.supabase_key),
                ("SUPABASE_STORAGE_BUCKET", settings.SUPABASE_STORAGE_BUCKET),
            )
            if not value
        ]
        if missing:
            # Names only. This message reaches logs.
            raise StorageError(
                "Supabase storage is selected but not configured. Missing: "
                + ", ".join(missing)
            )

        self.bucket = settings.SUPABASE_STORAGE_BUCKET
        self.base_url = str(settings.SUPABASE_URL).rstrip("/")

        if client is not None:
            self._client = client
            return

        import httpx

        key = settings.supabase_key
        self._client = httpx.Client(
            timeout=self.TIMEOUT_SECONDS,
            headers={
                # Storage reads the credential from Authorization; `apikey` is sent
                # too because the gateway in front of it expects one. Both carry
                # the same value, which is what the Supabase clients do.
                "Authorization": f"Bearer {key}",
                "apikey": key,
            },
        )

    def _object_url(self, key: str) -> str:
        _reject_traversal(key)
        return f"{self.base_url}/storage/v1/object/{self.bucket}/{key}"

    def save(self, key: str, source: BinaryIO) -> None:
        url = self._object_url(key)
        try:
            response = self._client.post(
                url,
                content=source.read(),
                headers={
                    "Content-Type": "application/octet-stream",
                    # Replace rather than fail when a key somehow repeats.
                    "x-upsert": "true",
                },
            )
        except Exception as error:
            logger.warning("storage upload failed", extra={"event": "storage_upload"})
            raise StorageError() from error

        if response.status_code >= 400:
            logger.warning(
                "storage upload rejected",
                extra={"event": "storage_upload", "status_code": response.status_code},
            )
            # No response body: it can echo the request, and the request is the
            # student's file.
            raise StorageError()

    def delete(self, key: str) -> None:
        try:
            response = self._client.delete(self._object_url(key))
        except Exception as error:
            raise StorageError("The file could not be removed.") from error

        # 404 means it is already gone, which is what delete promises.
        if response.status_code >= 400 and response.status_code != 404:
            raise StorageError("The file could not be removed.")

    def exists(self, key: str) -> bool:
        try:
            response = self._client.head(self._object_url(key))
        except Exception:
            # Treat an unreachable provider as "not present" rather than raising:
            # every caller of `exists` already handles a missing file, and a 500
            # on a transport blip would be worse than a 404.
            return False
        return response.status_code < 400

    def open(self, key: str) -> BinaryIO:
        """Fetch the object into memory and hand back a stream.

        Buffered rather than streamed end to end because uploads are capped at
        MAX_UPLOAD_BYTES (25 MB) and holding one in memory is bounded and simple.
        A true pass-through stream would keep an httpx response open across the
        FastAPI response lifecycle, which is a lifetime bug waiting to happen.
        """
        import io

        try:
            response = self._client.get(self._object_url(key))
        except Exception as error:
            raise StorageError("The file could not be read.") from error

        if response.status_code == 404:
            raise ResourceNotFoundError("Document file", key)
        if response.status_code >= 400:
            raise StorageError("The file could not be read.")

        return io.BytesIO(response.content)

    @contextmanager
    def local_path(self, key: str) -> Iterator[Path]:
        """Download to a temp file for code that needs a real path.

        Deleted on exit whether or not the block raised — extraction failures are
        routine (a corrupt PDF), and each one must not leave a copy of a student's
        document in the container's temp directory.
        """
        suffix = Path(key).suffix
        # noqa SIM115: the handle deliberately outlives this statement — it is
        # closed and unlinked in the `finally` below, after the caller's block.
        handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)  # noqa: SIM115
        try:
            with self.open(key) as source:
                shutil.copyfileobj(source, handle)
            handle.close()
            yield Path(handle.name)
        finally:
            handle.close()
            Path(handle.name).unlink(missing_ok=True)


def get_storage_service() -> StorageService:
    """Build the configured backend.

    `local` writes to UPLOAD_DIR. That is correct in development, and correct in
    production ONLY with a persistent volume attached: on an ephemeral filesystem
    — the default on most free tiers — uploaded documents disappear on every
    deploy while their database rows survive, leaving courses whose materials 404.

    `supabase` stores objects in a private bucket, which survives redeploys and is
    the intended production configuration.
    """
    if settings.STORAGE_BACKEND == "local":
        return LocalStorageService()
    if settings.STORAGE_BACKEND == "supabase":
        return SupabaseStorageService()

    # Unreachable while STORAGE_BACKEND is a constrained Literal, but a wrong
    # value must fail loudly rather than silently fall back to a backend that
    # loses data.
    raise ValueError(f"Unknown STORAGE_BACKEND: {settings.STORAGE_BACKEND!r}")
