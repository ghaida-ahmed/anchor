"""Flashcard review scheduling, the due queue, and review-driven mastery.

Everything here is database plus arithmetic. Nothing consults a model: what is due
is a query, and how the interval changes is `scheduling.schedule`.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.clock import now
from app.core.exceptions import ResourceNotFoundError
from app.core.timezones import local_day_bounds
from app.models import (
    Course,
    Flashcard,
    FlashcardReview,
    FlashcardReviewState,
    ReviewRating,
)
from app.services.learning.mastery_service import MasteryService
from app.services.learning.scheduling import (
    NEW_CARD,
    ScheduleState,
    describe_interval,
    schedule,
)

# A card due within this window counts as "upcoming" for the dashboard.
UPCOMING_HORIZON_DAYS = 7


@dataclass(frozen=True)
class DueSummary:
    """What the Flashcards page needs to decide what to show first."""

    due_now: int
    overdue: int
    upcoming: int
    total: int
    never_reviewed: int


@dataclass(frozen=True)
class ReviewOutcome:
    state: FlashcardReviewState
    next_review_label: str


class ReviewService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.mastery = MasteryService(session)

    # --- Queue -----------------------------------------------------------------

    def summary(
        self,
        user_id: uuid.UUID,
        course_id: uuid.UUID,
        *,
        at: datetime | None = None,
        timezone: str | None = None,
    ) -> DueSummary:
        """Counts for the due dashboard. One query per bucket, all index-backed.

        The buckets are LOCAL-DAY boundaries, not offsets from the current instant.
        "Due" means due before the end of the student's day, so a card scheduled for
        tonight is in this morning's queue rather than appearing at 22:00. "Overdue"
        means it was due before today began. Both boundaries are computed in the
        student's own timezone, so they land where their day actually starts and
        end up an hour apart across a DST change rather than 24 hours apart.
        """
        self._assert_course_owned(user_id, course_id)
        moment = at or now()
        day_start, day_end = local_day_bounds(timezone, at=moment)

        total = self._count(user_id, course_id)
        # A card with no review state has never been seen, so it is due.
        never = self._count(user_id, course_id, unseen_only=True)
        due = self._count(user_id, course_id, due_before=day_end) + never
        overdue = self._count(user_id, course_id, overdue_before=day_start)
        upcoming = self._count(
            user_id, course_id, upcoming_from=day_end, horizon_days=UPCOMING_HORIZON_DAYS
        )

        return DueSummary(
            due_now=due,
            overdue=overdue,
            upcoming=upcoming,
            total=total,
            never_reviewed=never,
        )

    def due_queue(
        self,
        user_id: uuid.UUID,
        course_id: uuid.UUID,
        *,
        topic_id: uuid.UUID | None = None,
        limit: int = 30,
        at: datetime | None = None,
        timezone: str | None = None,
    ) -> list[Flashcard]:
        """Cards due today, most overdue first, then never-seen cards.

        "Today" ends at the student's local midnight, so the queue is stable for a
        whole day rather than trickling in card by card.

        Ownership is a predicate in the query, not a check afterwards.
        """
        self._assert_course_owned(user_id, course_id)
        moment = at or now()
        _, day_end = local_day_bounds(timezone, at=moment)

        query = (
            select(Flashcard)
            .join(Course, Course.id == Flashcard.course_id)
            .outerjoin(
                FlashcardReviewState,
                (FlashcardReviewState.flashcard_id == Flashcard.id)
                & (FlashcardReviewState.user_id == user_id),
            )
            .where(
                Course.user_id == user_id,
                Flashcard.course_id == course_id,
                Flashcard.user_id == user_id,
                or_(
                    FlashcardReviewState.id.is_(None),
                    FlashcardReviewState.due_at.is_(None),
                    FlashcardReviewState.due_at <= day_end,
                ),
            )
            # Nulls last puts never-seen cards after genuinely overdue ones.
            .order_by(FlashcardReviewState.due_at.asc().nullslast())
            .limit(limit)
        )
        if topic_id is not None:
            query = query.where(Flashcard.topic_id == topic_id)

        return list(self.session.scalars(query))

    def due_by_topic(
        self,
        user_id: uuid.UUID,
        course_id: uuid.UUID,
        *,
        at: datetime | None = None,
        timezone: str | None = None,
    ) -> dict[uuid.UUID, int]:
        """Due card counts per topic, for the adaptive selector's review pressure.

        Same local-day boundary as `due_queue`, so the review pressure the adaptive
        engine sees matches the queue the student is looking at.
        """
        moment = at or now()
        _, day_end = local_day_bounds(timezone, at=moment)

        rows = self.session.execute(
            select(Flashcard.topic_id, func.count(Flashcard.id))
            .join(Course, Course.id == Flashcard.course_id)
            .outerjoin(
                FlashcardReviewState,
                (FlashcardReviewState.flashcard_id == Flashcard.id)
                & (FlashcardReviewState.user_id == user_id),
            )
            .where(
                Course.user_id == user_id,
                Flashcard.course_id == course_id,
                Flashcard.user_id == user_id,
                or_(
                    FlashcardReviewState.id.is_(None),
                    FlashcardReviewState.due_at.is_(None),
                    FlashcardReviewState.due_at <= day_end,
                ),
            )
            .group_by(Flashcard.topic_id)
        ).all()

        return {topic_id: count for topic_id, count in rows}

    # --- Reviewing -------------------------------------------------------------

    def review(
        self,
        *,
        user_id: uuid.UUID,
        flashcard_id: uuid.UUID,
        rating: ReviewRating,
        at: datetime | None = None,
    ) -> ReviewOutcome:
        """Record one rating: reschedule the card and update topic mastery."""
        moment = at or now()

        # Ownership through the card's own user column AND its course, so neither
        # a shared course nor a stray card id opens a path in.
        card = self.session.scalar(
            select(Flashcard)
            .join(Course, Course.id == Flashcard.course_id)
            .where(
                Flashcard.id == flashcard_id,
                Flashcard.user_id == user_id,
                Course.user_id == user_id,
            )
        )
        if card is None:
            raise ResourceNotFoundError("Flashcard", str(flashcard_id))

        state = self.session.scalar(
            select(FlashcardReviewState).where(
                FlashcardReviewState.user_id == user_id,
                FlashcardReviewState.flashcard_id == card.id,
            )
        )
        if state is None:
            state = FlashcardReviewState(
                user_id=user_id,
                flashcard_id=card.id,
                course_id=card.course_id,
                topic_id=card.topic_id,
            )
            self.session.add(state)
            self.session.flush()

        updated = schedule(_schedule_state(state), rating, at=moment)

        state.interval_days = updated.interval_days
        state.ease = updated.ease
        state.review_count = updated.review_count
        state.success_count = updated.success_count
        state.lapses = updated.lapses
        state.last_reviewed_at = updated.last_reviewed_at
        state.due_at = updated.due_at

        self.session.add(
            FlashcardReview(
                state_id=state.id,
                user_id=user_id,
                rating=rating,
                reviewed_at=moment,
                interval_days_after=updated.interval_days,
            )
        )

        self.mastery.record_flashcard_review(
            user_id=user_id,
            course_id=card.course_id,
            topic_id=card.topic_id,
            rating=rating.value,
            reviewed_at=moment,
            source_id=card.id,
        )

        self.session.commit()
        self.session.refresh(state)

        return ReviewOutcome(state=state, next_review_label=describe_interval(updated))

    def state_for(
        self, user_id: uuid.UUID, flashcard_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, FlashcardReviewState]:
        if not flashcard_ids:
            return {}
        rows = self.session.scalars(
            select(FlashcardReviewState).where(
                FlashcardReviewState.user_id == user_id,
                FlashcardReviewState.flashcard_id.in_(flashcard_ids),
            )
        )
        return {row.flashcard_id: row for row in rows}

    # --- Internals -------------------------------------------------------------

    def _count(
        self,
        user_id: uuid.UUID,
        course_id: uuid.UUID,
        *,
        unseen_only: bool = False,
        due_before: datetime | None = None,
        overdue_before: datetime | None = None,
        upcoming_from: datetime | None = None,
        horizon_days: int = 0,
    ) -> int:
        from datetime import timedelta

        query = (
            select(func.count(Flashcard.id))
            .join(Course, Course.id == Flashcard.course_id)
            .outerjoin(
                FlashcardReviewState,
                (FlashcardReviewState.flashcard_id == Flashcard.id)
                & (FlashcardReviewState.user_id == user_id),
            )
            .where(
                Course.user_id == user_id,
                Flashcard.course_id == course_id,
                Flashcard.user_id == user_id,
            )
        )

        if unseen_only:
            query = query.where(
                or_(
                    FlashcardReviewState.id.is_(None),
                    FlashcardReviewState.due_at.is_(None),
                )
            )
        elif due_before is not None:
            query = query.where(FlashcardReviewState.due_at <= due_before)
        elif overdue_before is not None:
            # "Overdue" means it was already due before today started in the
            # student's timezone; a card that came due this morning is due, not
            # overdue. The caller passes the local day boundary, so no arithmetic
            # on instants happens here.
            query = query.where(FlashcardReviewState.due_at < overdue_before)
        elif upcoming_from is not None:
            query = query.where(
                FlashcardReviewState.due_at > upcoming_from,
                FlashcardReviewState.due_at
                <= upcoming_from + timedelta(days=horizon_days),
            )

        return self.session.scalar(query) or 0

    def _assert_course_owned(self, user_id: uuid.UUID, course_id: uuid.UUID) -> None:
        owned = self.session.scalar(
            select(Course.id).where(Course.id == course_id, Course.user_id == user_id)
        )
        if owned is None:
            raise ResourceNotFoundError("Course", str(course_id))


def _schedule_state(row: FlashcardReviewState) -> ScheduleState:
    if row.review_count == 0 and row.due_at is None:
        return NEW_CARD
    return ScheduleState(
        interval_days=row.interval_days,
        ease=row.ease,
        review_count=row.review_count,
        success_count=row.success_count,
        lapses=row.lapses,
        last_reviewed_at=row.last_reviewed_at,
        due_at=row.due_at,
    )
