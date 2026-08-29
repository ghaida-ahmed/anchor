"""Domain exceptions and the HTTP responses they map to.

Services raise these; they never import FastAPI. The handlers registered at the
bottom are the single place where a domain failure becomes a status code, so error
responses stay consistent across every endpoint.

Every response body carries a `detail` string suitable for showing to a user.
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError


class AnchorError(Exception):
    """Base class for errors raised by the service layer."""

    status_code: int = status.HTTP_400_BAD_REQUEST


class NotImplementedInPhaseError(AnchorError):
    """Raised by a route whose service layer is not built yet.

    Placeholder routes exist so the API surface and its schemas are settled early.
    They answer honestly with 501 rather than returning invented data.
    """

    status_code = status.HTTP_501_NOT_IMPLEMENTED

    def __init__(self, feature: str, phase: str) -> None:
        self.feature = feature
        self.phase = phase
        super().__init__(f"{feature} is not implemented yet (planned for {phase}).")


class ResourceNotFoundError(AnchorError):
    status_code = status.HTTP_404_NOT_FOUND

    def __init__(self, resource: str, identifier: str) -> None:
        self.resource = resource
        self.identifier = identifier
        super().__init__(f"{resource} '{identifier}' was not found.")


class AuthenticationError(AnchorError):
    """Bad credentials, or a missing/expired/invalid token."""

    status_code = status.HTTP_401_UNAUTHORIZED

    def __init__(
        self, message: str = "Could not authenticate with those details."
    ) -> None:
        super().__init__(message)


class PermissionDeniedError(AnchorError):
    """Authenticated, but the resource belongs to someone else."""

    status_code = status.HTTP_403_FORBIDDEN

    def __init__(self, message: str = "You do not have access to this resource.") -> None:
        super().__init__(message)


class DuplicateResourceError(AnchorError):
    status_code = status.HTTP_409_CONFLICT

    def __init__(self, message: str) -> None:
        super().__init__(message)


class InvalidUploadError(AnchorError):
    """Rejected file: wrong type, empty, or over the size limit."""

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT

    def __init__(self, message: str) -> None:
        super().__init__(message)


class ServiceUnavailableError(AnchorError):
    """A capability the server depends on is not configured or reachable."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE


class StorageError(AnchorError):
    """The storage backend failed to save or remove a file."""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(self, message: str = "The file could not be stored.") -> None:
        super().__init__(message)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotImplementedInPhaseError)
    async def _not_implemented(
        _request: Request, exc: NotImplementedInPhaseError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": str(exc),
                "feature": exc.feature,
                "planned_phase": exc.phase,
            },
        )

    @app.exception_handler(AuthenticationError)
    async def _unauthenticated(
        _request: Request, exc: AuthenticationError
    ) -> JSONResponse:
        # WWW-Authenticate is required by RFC 9110 on a 401.
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": str(exc)},
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.exception_handler(AnchorError)
    async def _domain_error(_request: Request, exc: AnchorError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    @app.exception_handler(SQLAlchemyError)
    async def _database_error(_request: Request, _exc: SQLAlchemyError) -> JSONResponse:
        # Never surface driver text: it leaks schema details and connection strings.
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "A database error occurred. Please try again."},
        )
