import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.timezones import DEFAULT_TIMEZONE, is_valid_timezone
from app.schemas.common import ORMModel


class UserRead(ORMModel):
    """Public shape of a user. `hashed_password` is absent by construction — the
    response model, not the ORM row, decides what leaves the API."""

    id: uuid.UUID
    name: str
    email: EmailStr
    timezone: str
    created_at: datetime


class TimezoneUpdate(BaseModel):
    """The student's own timezone, as an IANA identifier.

    A NAME, never a fixed offset. "Europe/London" carries the rule that the clock
    changes on the last Sunday in March; "UTC+1" carries only today's arithmetic
    and is wrong for half the year. Storing an offset would also break the moment
    the government of the day changed the rules.

    The client sends what the browser reports, which is a timezone and not a
    location: `Europe/London` says nothing about where in the country someone is,
    and nothing is inferred from an IP address.
    """

    timezone: str = Field(min_length=1, max_length=64, examples=["Europe/London"])

    @field_validator("timezone")
    @classmethod
    def _known_zone(cls, value: str) -> str:
        candidate = value.strip()
        if not is_valid_timezone(candidate):
            raise ValueError(
                f"Unknown timezone. Use an IANA identifier such as "
                f"'Europe/London' or '{DEFAULT_TIMEZONE}'."
            )
        return candidate
