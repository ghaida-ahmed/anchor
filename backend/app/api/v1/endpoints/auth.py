"""Authentication endpoints.

Stateless JWT: there is no server-side session to destroy, so logout is a client
action (discard the token). No `/logout` route exists rather than one that pretends
to revoke something. Token revocation would need a denylist — noted in the README.
"""

from fastapi import APIRouter, status

from app.api.deps import AuthServiceDep, CurrentUser, SessionDep
from app.core.config import settings
from app.core.security import TOKEN_TYPE, create_access_token
from app.models import User
from app.schemas import (
    LoginRequest,
    RegisterRequest,
    TimezoneUpdate,
    TokenResponse,
    UserRead,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _issue_token(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id),
        token_type=TOKEN_TYPE,
        expires_in=settings.ACCESS_TOKEN_TTL_MINUTES * 60,
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"description": "Email already registered."}},
    summary="Create an account",
)
def register(service: AuthServiceDep, payload: RegisterRequest) -> TokenResponse:
    """Registers and signs in, so the client does not have to call login next."""
    return _issue_token(service.register(payload))


@router.post(
    "/login",
    response_model=TokenResponse,
    responses={status.HTTP_401_UNAUTHORIZED: {"description": "Invalid credentials."}},
    summary="Exchange credentials for an access token",
)
def login(service: AuthServiceDep, payload: LoginRequest) -> TokenResponse:
    return _issue_token(service.authenticate(payload))


@router.get(
    "/me",
    response_model=UserRead,
    responses={status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated."}},
    summary="The signed-in user",
)
def read_current_user(user: CurrentUser) -> User:
    return user


@router.patch(
    "/me/timezone",
    response_model=UserRead,
    status_code=status.HTTP_200_OK,
    responses={status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated."}},
    summary="Set the signed-in student's timezone",
)
def update_timezone(
    session: SessionDep, user: CurrentUser, payload: TimezoneUpdate
) -> User:
    """Store an IANA timezone for this account.

    Only the identifier is stored. It is a timezone, not a location: it is enough
    to know when this student's day starts, and it is not precise enough to say
    where they are. Nothing is inferred from an IP address, and the client sends
    what the browser already knows rather than being asked to locate itself.

    Timestamps everywhere else stay UTC. This value affects only where day
    boundaries fall — the review queue, the activity chart and the exam countdown.
    """
    user.timezone = payload.timezone
    session.commit()
    session.refresh(user)
    return user
