from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.security import MAX_PASSWORD_BYTES

MIN_PASSWORD_LENGTH = 8


class _PasswordField(BaseModel):
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)

    @field_validator("password")
    @classmethod
    def _within_bcrypt_limit(cls, value: str) -> str:
        # bcrypt ignores bytes past 72, which would make two long passwords
        # interchangeable. Reject instead of silently truncating.
        if len(value.encode()) > MAX_PASSWORD_BYTES:
            raise ValueError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes long.")
        return value


class RegisterRequest(_PasswordField):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr


class LoginRequest(_PasswordField):
    email: EmailStr


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
