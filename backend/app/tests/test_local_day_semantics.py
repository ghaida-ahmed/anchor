"""The timezone-dependent behaviour of the review queue, analytics and exam countdown.

These are the places where a UTC day boundary would give a student in Tokyo or Los
Angeles a visibly wrong answer.
"""

import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.clock import frozen_time
from app.models import (
    Course,
    Flashcard,
    FlashcardReviewState,
    MasteryEvent,
    MasteryEventSource,
    User,
)
from app.services.learning.analytics import AnalyticsService
from app.services.learning.exam import days_until
from app.services.learning.review_service import ReviewService
from app.tests.conftest import make_topic, unique_email

UTC = ZoneInfo("UTC")


def _course(session: Session) -> tuple[User, Course]:
    user = User(
        name="Local Day",
        email=unique_email("localday"),
        hashed_password="not-a-real-hash",
    )
    course = Course(title="Networks", code="CS340", description="")
    user.courses.append(course)
    session.add(user)
    session.flush()
    return user, course


class TestReviewQueue:
    def test_a_card_due_later_today_is_already_in_todays_queue(
        self, session: Session
    ) -> None:
        """Opening ANCHOR in the morning shows the whole day's work, rather than
        trickling cards in as their instants pass."""
        user, course = _course(session)
        topic = make_topic(session, course.id, "Slow Start", "Doubling the window.")
        card = Flashcard(
            user_id=user.id,
            course_id=course.id,
            topic_id=topic.id,
            front="Q",
            back="A",
        )
        session.add(card)
        session.flush()
        session.add(
            FlashcardReviewState(
                user_id=user.id,
                flashcard_id=card.id,
                course_id=course.id,
                topic_id=topic.id,
                due_at=datetime(2026, 6, 15, 21, 0, tzinfo=UTC),
            )
        )
        session.flush()

        morning = datetime(2026, 6, 15, 8, 0, tzinfo=UTC)
        reviews = ReviewService(session)
        summary = reviews.summary(user.id, course.id, at=morning, timezone="UTC")
        assert summary.due_now == 1

        queue = reviews.due_queue(user.id, course.id, at=morning, timezone="UTC")
        assert [item.id for item in queue] == [card.id]

    def test_the_boundary_moves_with_the_students_timezone(
        self, session: Session
    ) -> None:
        """A card due at 03:00 UTC on 17 June is tomorrow's work in UTC, but it is
        20:00 on the 16th in Los Angeles — still the student's evening, so it
        belongs to today's queue for them and not for a student on UTC."""
        user, course = _course(session)
        topic = make_topic(session, course.id, "Slow Start", "Doubling the window.")
        card = Flashcard(
            user_id=user.id,
            course_id=course.id,
            topic_id=topic.id,
            front="Q",
            back="A",
        )
        session.add(card)
        session.flush()
        session.add(
            FlashcardReviewState(
                user_id=user.id,
                flashcard_id=card.id,
                course_id=course.id,
                topic_id=topic.id,
                due_at=datetime(2026, 6, 17, 3, 0, tzinfo=UTC),
            )
        )
        session.flush()

        # 22:00 on 16 June in UTC; 15:00 on 16 June in Los Angeles.
        moment = datetime(2026, 6, 16, 22, 0, tzinfo=UTC)
        reviews = ReviewService(session)

        in_utc = reviews.summary(user.id, course.id, at=moment, timezone="UTC")
        in_la = reviews.summary(
            user.id, course.id, at=moment, timezone="America/Los_Angeles"
        )
        assert in_utc.due_now == 0
        assert in_la.due_now == 1

    def test_overdue_means_due_before_today_began(self, session: Session) -> None:
        user, course = _course(session)
        topic = make_topic(session, course.id, "Slow Start", "Doubling the window.")
        cards = []
        for due in (
            datetime(2026, 6, 15, 2, 0, tzinfo=UTC),  # earlier today
            datetime(2026, 6, 13, 2, 0, tzinfo=UTC),  # two days ago
        ):
            card = Flashcard(
                user_id=user.id,
                course_id=course.id,
                topic_id=topic.id,
                front="Q",
                back="A",
            )
            session.add(card)
            session.flush()
            session.add(
                FlashcardReviewState(
                    user_id=user.id,
                    flashcard_id=card.id,
                    course_id=course.id,
                    topic_id=topic.id,
                    due_at=due,
                )
            )
            cards.append(card)
        session.flush()

        summary = ReviewService(session).summary(
            user.id,
            course.id,
            at=datetime(2026, 6, 15, 12, 0, tzinfo=UTC),
            timezone="UTC",
        )
        assert summary.due_now == 2
        # Only the genuinely old one is overdue; this morning's is simply due.
        assert summary.overdue == 1


class TestAnalyticsGrouping:
    def _event(self, user, course, topic_id, moment) -> MasteryEvent:
        return MasteryEvent(
            user_id=user.id,
            course_id=course.id,
            topic_id=topic_id,
            source_type=MasteryEventSource.QUIZ_ANSWER,
            source_id=uuid.uuid4(),
            previous_raw_score=0.0,
            new_raw_score=30.0,
            previous_mastery=0.0,
            new_mastery=18.0,
            effective_mastery_at_event=18.0,
            was_correct=True,
            difficulty=None,
            questions_attempted_after=1,
            created_at=moment,
        )

    def test_two_evening_answers_are_one_local_day_not_two(
        self, session: Session
    ) -> None:
        """21:00 and 23:00 in Los Angeles are 04:00 and 06:00 the next day in UTC.
        Grouped by UTC they split across two bars; the student studied once."""
        user, course = _course(session)
        topic = make_topic(session, course.id, "Slow Start", "Doubling the window.")

        session.add(
            self._event(user, course, topic.id, datetime(2026, 6, 16, 4, 0, tzinfo=UTC))
        )
        session.add(
            self._event(user, course, topic.id, datetime(2026, 6, 16, 6, 0, tzinfo=UTC))
        )
        session.flush()

        analytics = AnalyticsService(session)

        in_utc = analytics.for_course(user.id, course.id, timezone="UTC")
        assert in_utc.active_days == 1
        assert in_utc.daily[0].day == date(2026, 6, 16)

        in_la = analytics.for_course(user.id, course.id, timezone="America/Los_Angeles")
        assert in_la.active_days == 1
        assert in_la.daily[0].day == date(2026, 6, 15)
        assert in_la.daily[0].answers == 2

    def test_a_utc_day_can_split_into_two_local_days(self, session: Session) -> None:
        user, course = _course(session)
        topic = make_topic(session, course.id, "Slow Start", "Doubling the window.")

        # Both on 16 June in UTC; 16th and 17th in Tokyo.
        session.add(
            self._event(user, course, topic.id, datetime(2026, 6, 16, 6, 0, tzinfo=UTC))
        )
        session.add(
            self._event(user, course, topic.id, datetime(2026, 6, 16, 16, 0, tzinfo=UTC))
        )
        session.flush()

        analytics = AnalyticsService(session)
        assert analytics.for_course(user.id, course.id, timezone="UTC").active_days == 1
        assert (
            analytics.for_course(user.id, course.id, timezone="Asia/Tokyo").active_days
            == 2
        )


class TestExamCountdown:
    def test_the_countdown_uses_the_students_today(self, session: Session) -> None:
        from app.core.timezones import local_date
        from app.services.learning.exam_service import ExamService

        user, course = _course(session)
        course.exam_date = date(2026, 6, 20)
        session.flush()

        # 22:00 on 15 June in Los Angeles is already 05:00 on the 16th in UTC.
        moment = datetime(2026, 6, 16, 5, 0, tzinfo=UTC)
        assert local_date("UTC", at=moment) == date(2026, 6, 16)
        assert local_date("America/Los_Angeles", at=moment) == date(2026, 6, 15)

        service = ExamService(session)
        in_utc = service.status(user.id, course.id, at=moment, timezone="UTC")
        in_la = service.status(
            user.id, course.id, at=moment, timezone="America/Los_Angeles"
        )
        assert in_utc.days_remaining == 4
        assert in_la.days_remaining == 5

    def test_a_countdown_is_in_calendar_days_not_multiples_of_24_hours(self) -> None:
        """Across a DST change, two calendar days are 47 hours."""
        assert days_until(date(2026, 3, 30), date(2026, 3, 28)) == 2


class TestClockInjectionStillWorks:
    def test_frozen_time_and_timezones_compose(self, session: Session) -> None:
        from app.core.timezones import local_date

        with frozen_time(datetime(2026, 6, 16, 5, 0, tzinfo=UTC)):
            assert local_date("UTC") == date(2026, 6, 16)
            assert local_date("America/Los_Angeles") == date(2026, 6, 15)
