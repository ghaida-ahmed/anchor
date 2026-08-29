import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel


def _blank_to_empty(value: str | None) -> str | None:
    """Treat whitespace-only optional text as absent."""
    return value.strip() if value else value


class CourseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    code: str = Field(default="", max_length=32)
    description: str = Field(default="", max_length=2000)

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Title must not be blank.")
        return stripped

    @field_validator("code", "description")
    @classmethod
    def _strip_optional(cls, value: str) -> str:
        return value.strip()


class CourseUpdate(BaseModel):
    """All fields optional — a PATCH may carry any subset."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("Title must not be blank.")
        return stripped

    @field_validator("code", "description")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        return _blank_to_empty(value)


class CourseRead(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    code: str
    description: str
    created_at: datetime
    updated_at: datetime


class CourseWithCounts(CourseRead):
    """Course plus the aggregate the course list and dashboard display."""

    document_count: int
