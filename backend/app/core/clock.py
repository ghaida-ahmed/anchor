"""The single source of "now".

Time-based learning features are only testable if time is injectable, and only
trustworthy if every part of the system agrees on what time it is. Both are
achieved by routing every wall-clock read through `now()`.

This is deliberately NOT monkey-patching `datetime.now` across modules: production
code calls one documented function, and tests replace that function's source for a
bounded scope via `frozen_time`.

Everything is UTC and timezone-aware. Naive datetimes never enter the system.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

_override: datetime | None = None


def now() -> datetime:
    """Current instant, timezone-aware UTC.

    Returns the frozen instant when inside `frozen_time`.
    """
    return _override if _override is not None else datetime.now(UTC)


@contextmanager
def frozen_time(instant: datetime) -> Iterator[datetime]:
    """Pin `now()` for the duration of the block. Test-only.

    Nesting restores the previous value rather than clearing, so a timeline can be
    stepped through in nested scopes.
    """
    global _override

    if instant.tzinfo is None:
        raise ValueError("frozen_time requires a timezone-aware instant.")

    previous = _override
    _override = instant.astimezone(UTC)
    try:
        yield _override
    finally:
        _override = previous


def ensure_utc(value: datetime) -> datetime:
    """Coerce a datetime to aware UTC.

    PostgreSQL returns aware datetimes for `timestamptz`, but a value that has been
    round-tripped through some drivers or fixtures can arrive naive. Comparing a
    naive and an aware datetime raises, so every boundary that reads a stored
    timestamp passes it through here.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def days_between(earlier: datetime, later: datetime) -> float:
    """Fractional days from `earlier` to `later`. Never negative."""
    delta = (ensure_utc(later) - ensure_utc(earlier)).total_seconds() / 86_400.0
    return max(0.0, delta)
