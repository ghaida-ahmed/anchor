"""User timezone handling.

Storage stays UTC everywhere — this module only converts *boundaries*. The rule
throughout ANCHOR is:

    a local-day boundary is computed in the user's zone,
    converted to UTC,
    and then compared against the UTC timestamps already in the database.

Nothing is stored twice, and no column holds a local time. That keeps a change of
timezone from rewriting history: only the boundaries move.

DST is handled by `zoneinfo` (the IANA database shipped with Python), never by
arithmetic on fixed offsets. A day is not always 24 hours long, and pretending
otherwise breaks twice a year.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from app.core.clock import ensure_utc, now

DEFAULT_TIMEZONE = "UTC"


def is_valid_timezone(name: str) -> bool:
    """Whether `name` is a known IANA identifier.

    Checked against the tz database rather than a hand-written list: fixed offsets
    like "UTC+3" are deliberately rejected, because they cannot express DST.
    """
    if not name or not isinstance(name, str):
        return False
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return False
    return name in available_timezones()


def zone_for(name: str | None) -> ZoneInfo:
    """Resolve a stored preference, falling back to UTC rather than raising.

    A zone that vanished from the tz database between releases must not break a
    dashboard; the fallback keeps the app working and the user can re-save.
    """
    if name and is_valid_timezone(name):
        return ZoneInfo(name)
    return ZoneInfo(DEFAULT_TIMEZONE)


def local_date(timezone: str | None, *, at: datetime | None = None) -> date:
    """The calendar date it currently is for this user."""
    return ensure_utc(at or now()).astimezone(zone_for(timezone)).date()


def local_day_bounds(
    timezone: str | None, day: date | None = None, *, at: datetime | None = None
) -> tuple[datetime, datetime]:
    """The UTC instants bracketing one local day: [start, end).

    Built by localising midnight in the user's zone and converting, so a day that
    is 23 or 25 hours long because of a DST transition comes out the right length.
    """
    zone = zone_for(timezone)
    target = day or local_date(timezone, at=at)

    start_local = datetime.combine(target, time.min, tzinfo=zone)
    # Adding a day to the DATE and re-localising is correct across DST; adding 24
    # hours to the instant is not.
    end_local = datetime.combine(target + timedelta(days=1), time.min, tzinfo=zone)

    return start_local.astimezone(ZoneInfo("UTC")), end_local.astimezone(ZoneInfo("UTC"))


def local_day_of(moment: datetime, timezone: str | None) -> date:
    """Which local calendar day a stored UTC timestamp falls on."""
    return ensure_utc(moment).astimezone(zone_for(timezone)).date()


def days_until_local(
    target: date, timezone: str | None, *, at: datetime | None = None
) -> int:
    """Whole days from the user's today to `target`. Negative once it has passed."""
    return (target - local_date(timezone, at=at)).days
