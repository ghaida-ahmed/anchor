"""Progress analytics, derived entirely from persisted events.

Every number here comes from `mastery_events`, `quiz_attempts` or the mastery table.
Nothing is interpolated, and no model is called: these load on every visit to the
Progress page.

AGGREGATION
-----------

Daily buckets, keyed by UTC calendar date. A day on which the student did nothing
produces NO bucket — it is absent from the series rather than carrying a zero or a
value carried forward. Drawing a flat line through an idle week would imply practice
that did not happen; the frontend renders gaps as gaps.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import ensure_utc
from app.core.exceptions import ResourceNotFoundError
from app.core.timezones import local_day_of
from app.models import Course, MasteryEvent, Quiz, QuizAttempt


@dataclass(frozen=True)
class DailyPoint:
    """One day on which something actually happened."""

    day: date
    answers: int
    correct: int
    # Mean mastery across topics touched that day, as recorded at the time.
    mean_mastery: float


@dataclass(frozen=True)
class TopicTrend:
    topic_id: uuid.UUID
    topic_name: str
    first_mastery: float
    latest_mastery: float

    @property
    def change(self) -> float:
        return self.latest_mastery - self.first_mastery


@dataclass(frozen=True)
class CourseAnalytics:
    daily: list[DailyPoint]
    topic_trends: list[TopicTrend]
    most_improved: TopicTrend | None
    total_events: int
    active_days: int
    first_activity: datetime | None
    last_activity: datetime | None


class AnalyticsService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def for_course(
        self,
        user_id: uuid.UUID,
        course_id: uuid.UUID,
        *,
        at: datetime | None = None,
        timezone: str | None = None,
    ) -> CourseAnalytics:
        """The activity chart and topic trends for one course.

        Events are stored as UTC instants and grouped into the student's LOCAL
        days. Grouping by UTC date would put an 11pm answer in Los Angeles on the
        following day's bar, so a student who studies in the evening would see
        their streak split across two days and their busiest day attributed to the
        wrong one.
        """
        self._assert_course_owned(user_id, course_id)

        events = list(
            self.session.scalars(
                select(MasteryEvent)
                .where(
                    MasteryEvent.user_id == user_id,
                    MasteryEvent.course_id == course_id,
                )
                .order_by(MasteryEvent.created_at)
            )
        )

        if not events:
            return CourseAnalytics([], [], None, 0, 0, None, None)

        by_day: dict[date, list[MasteryEvent]] = defaultdict(list)
        for event in events:
            by_day[local_day_of(event.created_at, timezone)].append(event)

        daily = [
            DailyPoint(
                day=day,
                answers=len(rows),
                correct=sum(1 for row in rows if row.was_correct),
                mean_mastery=round(sum(row.new_mastery for row in rows) / len(rows), 1),
            )
            for day, rows in sorted(by_day.items())
        ]

        trends = self._topic_trends(events)
        improved = max(trends, key=lambda t: t.change, default=None)

        return CourseAnalytics(
            daily=daily,
            topic_trends=trends,
            most_improved=improved if improved and improved.change > 0 else None,
            total_events=len(events),
            active_days=len(by_day),
            first_activity=ensure_utc(events[0].created_at),
            last_activity=ensure_utc(events[-1].created_at),
        )

    def recent_attempts_accuracy(
        self, user_id: uuid.UUID, course_id: uuid.UUID, *, limit: int = 10
    ) -> list[tuple[datetime, float]]:
        """Completed attempt scores, oldest first — the "am I improving?" series."""
        rows = self.session.execute(
            select(QuizAttempt.completed_at, QuizAttempt.score_percent)
            .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
            .where(
                Quiz.course_id == course_id,
                QuizAttempt.user_id == user_id,
                QuizAttempt.completed_at.is_not(None),
                QuizAttempt.score_percent.is_not(None),
            )
            .order_by(QuizAttempt.completed_at.desc())
            .limit(limit)
        ).all()

        return [(ensure_utc(when), score) for when, score in reversed(rows)]

    @staticmethod
    def _topic_trends(events: list[MasteryEvent]) -> list[TopicTrend]:
        first: dict[uuid.UUID, MasteryEvent] = {}
        last: dict[uuid.UUID, MasteryEvent] = {}
        names: dict[uuid.UUID, str] = {}

        for event in events:
            first.setdefault(event.topic_id, event)
            last[event.topic_id] = event
            if event.topic is not None:
                names[event.topic_id] = event.topic.name

        return sorted(
            (
                TopicTrend(
                    topic_id=topic_id,
                    topic_name=names.get(topic_id, "Unknown topic"),
                    # The mastery BEFORE the first recorded event is where the
                    # student started, not the value after it.
                    first_mastery=first[topic_id].previous_mastery,
                    latest_mastery=last[topic_id].new_mastery,
                )
                for topic_id in first
            ),
            key=lambda trend: trend.topic_name.lower(),
        )

    def _assert_course_owned(self, user_id: uuid.UUID, course_id: uuid.UUID) -> None:
        owned = self.session.scalar(
            select(Course.id).where(Course.id == course_id, Course.user_id == user_id)
        )
        if owned is None:
            raise ResourceNotFoundError("Course", str(course_id))


__all__ = [
    "AnalyticsService",
    "CourseAnalytics",
    "DailyPoint",
    "TopicTrend",
]
