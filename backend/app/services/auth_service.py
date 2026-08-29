"""Registration, login and user lookup."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import (
    AuthenticationError,
    DuplicateResourceError,
    ResourceNotFoundError,
)
from app.core.security import hash_password, verify_password
from app.models import User
from app.schemas import LoginRequest, RegisterRequest


def normalize_email(email: str) -> str:
    """Emails are matched case-insensitively; store them lowercased."""
    return email.strip().lower()


class AuthService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def register(self, payload: RegisterRequest) -> User:
        email = normalize_email(payload.email)

        if self._find_by_email(email) is not None:
            raise DuplicateResourceError("An account with that email already exists.")

        user = User(
            name=payload.name.strip(),
            email=email,
            hashed_password=hash_password(payload.password),
        )
        self.session.add(user)

        try:
            self.session.commit()
        except IntegrityError as error:
            # Two concurrent registrations: the unique index is the real guard,
            # the check above is just a friendlier fast path.
            self.session.rollback()
            raise DuplicateResourceError(
                "An account with that email already exists."
            ) from error

        self.session.refresh(user)
        return user

    def authenticate(self, payload: LoginRequest) -> User:
        user = self._find_by_email(normalize_email(payload.email))

        # One message for both "no such user" and "wrong password" so the endpoint
        # cannot be used to enumerate registered addresses.
        if user is None or not verify_password(payload.password, user.hashed_password):
            raise AuthenticationError("Incorrect email or password.")

        return user

    def get(self, user_id: uuid.UUID) -> User:
        user = self.session.get(User, user_id)
        if user is None:
            raise ResourceNotFoundError("User", str(user_id))
        return user

    def _find_by_email(self, email: str) -> User | None:
        return self.session.scalar(select(User).where(func.lower(User.email) == email))
