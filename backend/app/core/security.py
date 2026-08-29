"""Password hashing and access-token handling.

bcrypt is used directly rather than through passlib: passlib has been unmaintained
for years and its bcrypt backend emits version-detection warnings on modern
releases. The API here is small enough that the wrapper earned nothing.
"""

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import settings

# bcrypt truncates silently at 72 bytes, which would make two different long
# passwords interchangeable. Reject rather than truncate.
MAX_PASSWORD_BYTES = 72

TOKEN_TYPE = "bearer"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed_password: str) -> bool:
    """False on malformed hashes rather than raising — callers treat it as a failure."""
    try:
        return bcrypt.checkpw(password.encode(), hashed_password.encode())
    except ValueError:
        return False


def create_access_token(user_id: uuid.UUID) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_TTL_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID | None:
    """Returns the subject, or None if the token is invalid, expired or malformed."""
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        return uuid.UUID(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        return None
