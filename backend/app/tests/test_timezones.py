"""IANA timezone handling and local-day semantics.

The DST assertions here are not decoration: a day is 23 or 25 hours long twice a
year, and every "days between" or "start of today" calculation in ANCHOR is wrong
if that is handled by adding 86400 seconds.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.core.timezones import (
    DEFAULT_TIMEZONE,
    days_until_local,
    is_valid_timezone,
    local_date,
    local_day_bounds,
    local_day_of,
    zone_for,
)
from app.tests.conftest import auth

UTC = ZoneInfo("UTC")


class TestValidation:
    def test_real_iana_names_are_accepted(self) -> None:
        for name in ("UTC", "Europe/London", "America/New_York", "Asia/Riyadh"):
            assert is_valid_timezone(name), name

    def test_fixed_offsets_are_rejected(self) -> None:
        """An offset cannot express DST, so it is not an acceptable substitute for
        a zone name — a student on 'UTC+1' would be an hour out for half the year."""
        for name in ("UTC+3", "+03:00", "GMT+2", "-0500"):
            assert not is_valid_timezone(name), name

    def test_nonsense_is_rejected(self) -> None:
        for name in ("", "   ", "Mars/Olympus", "Europe/Nowhere", "../../etc/passwd"):
            assert not is_valid_timezone(name), name

    def test_an_unknown_zone_falls_back_to_utc_rather_than_raising(self) -> None:
        """Reading data must never fail because a stored zone became unknown."""
        assert zone_for("Mars/Olympus") == ZoneInfo(DEFAULT_TIMEZONE)
        assert zone_for(None) == ZoneInfo(DEFAULT_TIMEZONE)


class TestLocalDays:
    def test_the_local_day_can_differ_from_the_utc_day(self) -> None:
        # 23:30 UTC on 1 March is already 08:30 on 2 March in Tokyo.
        evening = datetime(2026, 3, 1, 23, 30, tzinfo=UTC)
        assert local_day_of(evening, "UTC") == date(2026, 3, 1)
        assert local_day_of(evening, "Asia/Tokyo") == date(2026, 3, 2)

        # 03:00 UTC on 2 March is still 19:00 on 1 March in Los Angeles — the case
        # that puts an evening study session on the wrong day if grouped by UTC.
        early = datetime(2026, 3, 2, 3, 0, tzinfo=UTC)
        assert local_day_of(early, "UTC") == date(2026, 3, 2)
        assert local_day_of(early, "America/Los_Angeles") == date(2026, 3, 1)

    def test_day_bounds_bracket_the_local_day(self) -> None:
        start, end = local_day_bounds("Asia/Tokyo", date(2026, 3, 2))
        assert start == datetime(2026, 3, 1, 15, 0, tzinfo=UTC)
        assert end == datetime(2026, 3, 2, 15, 0, tzinfo=UTC)

    def test_local_date_uses_the_supplied_instant(self) -> None:
        moment = datetime(2026, 3, 1, 23, 30, tzinfo=UTC)
        assert local_date("Asia/Tokyo", at=moment) == date(2026, 3, 2)


class TestDaylightSaving:
    """London, 2026: clocks go forward on 29 March and back on 25 October."""

    def test_the_spring_forward_day_is_twenty_three_hours(self) -> None:
        start, end = local_day_bounds("Europe/London", date(2026, 3, 29))
        assert (end - start).total_seconds() / 3600 == 23

    def test_the_autumn_back_day_is_twenty_five_hours(self) -> None:
        start, end = local_day_bounds("Europe/London", date(2026, 10, 25))
        assert (end - start).total_seconds() / 3600 == 25

    def test_an_ordinary_day_is_twenty_four_hours(self) -> None:
        start, end = local_day_bounds("Europe/London", date(2026, 6, 15))
        assert (end - start).total_seconds() / 3600 == 24

    def test_a_countdown_across_a_dst_change_counts_calendar_days(self) -> None:
        """28 March to 30 March is two days, even though only 47 hours elapse."""
        at = datetime(2026, 3, 28, 12, 0, tzinfo=ZoneInfo("Europe/London"))
        assert days_until_local(date(2026, 3, 30), "Europe/London", at=at) == 2

    def test_utc_has_no_transitions(self) -> None:
        for day in (date(2026, 3, 29), date(2026, 10, 25)):
            start, end = local_day_bounds("UTC", day)
            assert (end - start).total_seconds() / 3600 == 24


class TestTimezonePreference:
    def test_a_new_account_defaults_to_utc(self, client: TestClient, token: str) -> None:
        response = client.get("/api/v1/auth/me", headers=auth(token))
        assert response.status_code == 200
        assert response.json()["timezone"] == "UTC"

    def test_setting_a_timezone_persists_it(self, client: TestClient, token: str) -> None:
        response = client.patch(
            "/api/v1/auth/me/timezone",
            json={"timezone": "Europe/London"},
            headers=auth(token),
        )
        assert response.status_code == 200
        assert response.json()["timezone"] == "Europe/London"

        again = client.get("/api/v1/auth/me", headers=auth(token))
        assert again.json()["timezone"] == "Europe/London"

    def test_a_fixed_offset_is_rejected(self, client: TestClient, token: str) -> None:
        response = client.patch(
            "/api/v1/auth/me/timezone",
            json={"timezone": "UTC+3"},
            headers=auth(token),
        )
        assert response.status_code == 422

    def test_an_unknown_zone_is_rejected(self, client: TestClient, token: str) -> None:
        response = client.patch(
            "/api/v1/auth/me/timezone",
            json={"timezone": "Mars/Olympus"},
            headers=auth(token),
        )
        assert response.status_code == 422

    def test_the_endpoint_requires_authentication(self, client: TestClient) -> None:
        response = client.patch(
            "/api/v1/auth/me/timezone", json={"timezone": "Europe/London"}
        )
        assert response.status_code == 401

    def test_one_students_timezone_does_not_affect_another(
        self, client: TestClient, token: str, other_token: str
    ) -> None:
        client.patch(
            "/api/v1/auth/me/timezone",
            json={"timezone": "Asia/Tokyo"},
            headers=auth(token),
        )
        other = client.get("/api/v1/auth/me", headers=auth(other_token))
        assert other.json()["timezone"] == "UTC"
