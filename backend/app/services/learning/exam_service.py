"""Exam date, readiness and exam-mode topic selection."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import now
from app.core.exceptions import ResourceNotFoundError
from app.core.timezones import local_date
from app.models import Course
from app.services.learning.adaptive import SelectedTopic, allocate_questions
from app.services.learning.exam import (
    ReadinessBreakdown,
    days_until,
    exam_priority,
    exam_readiness,
    topics_for_session,
)
from app.services.learning.mastery_service import MasteryService
from app.services.learning.review_service import ReviewService


@dataclass(frozen=True)
class ExamStatus:
    exam_date: date | None
    days_remaining: int | None
    has_passed: bool
    readiness: ReadinessBreakdown
    topics_needing_attention: list[str]


class ExamService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.mastery = MasteryService(session)
        self.reviews = ReviewService(session)

    def set_exam_date(
        self, user_id: uuid.UUID, course_id: uuid.UUID, exam_date: date | None
    ) -> Course:
        """Set, change or clear a course's exam date. Optional by design."""
        course = self._owned_course(user_id, course_id)
        course.exam_date = exam_date
        self.session.commit()
        self.session.refresh(course)
        return course

    def status(
        self,
        user_id: uuid.UUID,
        course_id: uuid.UUID,
        *,
        at: datetime | None = None,
        timezone: str | None = None,
    ) -> ExamStatus:
        """Readiness and countdown for one course.

        The countdown is in local days. An exam date is a calendar date, not an
        instant, so "days until" must be measured from the student's own today —
        otherwise a student in Tokyo is told they have two days left on the morning
        of the day before.
        """
        course = self._owned_course(user_id, course_id)
        moment = at or now()

        candidates = self.mastery.candidates_for(user_id, course_id, at=moment)
        summary = self.reviews.summary(user_id, course_id, at=moment)
        readiness = exam_readiness(
            candidates, overdue_cards=summary.overdue, total_cards=summary.total
        )

        remaining = days_until(course.exam_date, local_date(timezone, at=moment))
        attention = [
            candidate.name
            for candidate in sorted(
                candidates, key=lambda c: (-exam_priority(c), c.name.lower())
            )[:3]
            if exam_priority(candidate) > 0.25
        ]

        return ExamStatus(
            exam_date=course.exam_date,
            days_remaining=remaining,
            # A past exam is not an error; the course simply stops being urgent.
            has_passed=remaining is not None and remaining < 0,
            readiness=readiness,
            topics_needing_attention=attention,
        )

    def select_topics(
        self,
        user_id: uuid.UUID,
        course_id: uuid.UUID,
        *,
        question_count: int,
        at: datetime | None = None,
        timezone: str | None = None,
    ) -> tuple[list[SelectedTopic], int | None]:
        """Exam-mode topic selection: coverage first, widening as the date nears."""
        course = self._owned_course(user_id, course_id)
        moment = at or now()

        candidates = self.mastery.candidates_for(user_id, course_id, at=moment)
        if not candidates:
            return [], None

        remaining = days_until(course.exam_date, local_date(timezone, at=moment))
        # A passed exam falls back to the distant-exam breadth rather than the
        # maximum: cramming for an exam that has happened helps nobody.
        widening_input = None if remaining is None or remaining < 0 else remaining

        span = min(
            topics_for_session(widening_input, len(candidates)),
            question_count,
        )
        if span <= 0:
            return [], remaining

        ranked = sorted(candidates, key=lambda c: (-exam_priority(c), c.name.lower()))[
            :span
        ]
        counts = allocate_questions(question_count, len(ranked))

        selected = [
            SelectedTopic(
                topic_id=candidate.topic_id,
                name=candidate.name,
                question_count=count,
                priority=round(exam_priority(candidate), 4),
                band=candidate.effective_band,
                is_review=False,
            )
            for candidate, count in zip(ranked, counts, strict=True)
            if count > 0
        ]
        return selected, remaining

    def _owned_course(self, user_id: uuid.UUID, course_id: uuid.UUID) -> Course:
        course = self.session.scalar(
            select(Course).where(Course.id == course_id, Course.user_id == user_id)
        )
        if course is None:
            raise ResourceNotFoundError("Course", str(course_id))
        return course
