"""Retention endpoints: history, analytics, review scheduling and exam preparation.

Not one route here can reach Gemini. Everything is a query or arithmetic over stored
evidence, which is why the Progress and Exam pages cost nothing to open.
"""

import uuid

from fastapi import APIRouter, status

from app.api.deps import (
    AnalyticsServiceDep,
    CurrentUser,
    ExamServiceDep,
    MasteryServiceDep,
    ReviewServiceDep,
)
from app.models import ReviewRating
from app.schemas import (
    AttemptScoreRead,
    CourseAnalyticsRead,
    DailyActivityRead,
    DueSummaryRead,
    ExamDateUpdate,
    ExamStatusRead,
    MasteryEventRead,
    ReadinessRead,
    ReviewResultRead,
    ReviewSubmit,
    TopicTrendRead,
)

router = APIRouter(tags=["retention"])

_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated."},
    status.HTTP_404_NOT_FOUND: {"description": "Not found for this user."},
}


# --- History and analytics -----------------------------------------------------


@router.get(
    "/courses/{course_id}/mastery/history",
    response_model=list[MasteryEventRead],
    responses=_RESPONSES,
    summary="Mastery-changing events, oldest first",
)
def read_history(
    service: MasteryServiceDep, user: CurrentUser, course_id: uuid.UUID
) -> list[MasteryEventRead]:
    """Immutable history. `effective_mastery_at_event` is the value frozen at the
    time, so changing the decay heuristic never rewrites the past."""
    return [
        MasteryEventRead(
            id=event.id,
            topic_id=event.topic_id,
            topic_name=event.topic.name if event.topic else "",
            source_type=event.source_type.value,
            previous_mastery=round(event.previous_mastery, 1),
            new_mastery=round(event.new_mastery, 1),
            effective_mastery_at_event=round(event.effective_mastery_at_event, 1),
            was_correct=event.was_correct,
            difficulty=event.difficulty.value if event.difficulty else None,
            created_at=event.created_at,
        )
        for event in service.history_for_course(user.id, course_id)
    ]


@router.get(
    "/courses/{course_id}/analytics",
    response_model=CourseAnalyticsRead,
    responses=_RESPONSES,
    summary="Practice trends from persisted events",
)
def read_analytics(
    service: AnalyticsServiceDep, user: CurrentUser, course_id: uuid.UUID
) -> CourseAnalyticsRead:
    # Days are the student's own, so the chart's bars line up with their evenings.
    analytics = service.for_course(user.id, course_id, timezone=user.timezone)
    scores = service.recent_attempts_accuracy(user.id, course_id)

    return CourseAnalyticsRead(
        daily=[
            DailyActivityRead(
                day=point.day,
                answers=point.answers,
                correct=point.correct,
                mean_mastery=point.mean_mastery,
            )
            for point in analytics.daily
        ],
        attempt_scores=[
            AttemptScoreRead(completed_at=when, score_percent=round(score, 1))
            for when, score in scores
        ],
        topic_trends=[
            TopicTrendRead(
                topic_id=trend.topic_id,
                topic_name=trend.topic_name,
                first_mastery=round(trend.first_mastery, 1),
                latest_mastery=round(trend.latest_mastery, 1),
                change=round(trend.change, 1),
            )
            for trend in analytics.topic_trends
        ],
        most_improved_topic=(
            analytics.most_improved.topic_name if analytics.most_improved else None
        ),
        total_events=analytics.total_events,
        active_days=analytics.active_days,
        first_activity=analytics.first_activity,
        last_activity=analytics.last_activity,
    )


# --- Flashcard review ----------------------------------------------------------


@router.get(
    "/courses/{course_id}/flashcards/due",
    response_model=DueSummaryRead,
    responses=_RESPONSES,
    summary="How many cards are due, overdue and upcoming",
)
def read_due_summary(
    service: ReviewServiceDep, user: CurrentUser, course_id: uuid.UUID
) -> DueSummaryRead:
    summary = service.summary(user.id, course_id, timezone=user.timezone)
    return DueSummaryRead(
        due_now=summary.due_now,
        overdue=summary.overdue,
        upcoming=summary.upcoming,
        total=summary.total,
        never_reviewed=summary.never_reviewed,
    )


@router.post(
    "/flashcards/{flashcard_id}/reviews",
    response_model=ReviewResultRead,
    status_code=status.HTTP_201_CREATED,
    responses=_RESPONSES,
    summary="Rate a card and reschedule it",
)
def submit_review(
    service: ReviewServiceDep,
    user: CurrentUser,
    flashcard_id: uuid.UUID,
    payload: ReviewSubmit,
) -> ReviewResultRead:
    """The rating is the student's own judgement of recall.

    Asking a model whether the student remembered would be both expensive and less
    accurate than the person who just tried.
    """
    outcome = service.review(
        user_id=user.id,
        flashcard_id=flashcard_id,
        rating=ReviewRating(payload.rating),
    )
    return ReviewResultRead(
        flashcard_id=flashcard_id,
        next_review_label=outcome.next_review_label,
        due_at=outcome.state.due_at,
        interval_days=outcome.state.interval_days,
    )


# --- Exam preparation ----------------------------------------------------------


@router.get(
    "/courses/{course_id}/exam",
    response_model=ExamStatusRead,
    responses=_RESPONSES,
    summary="Exam date, readiness and what needs attention",
)
def read_exam_status(
    service: ExamServiceDep, user: CurrentUser, course_id: uuid.UUID
) -> ExamStatusRead:
    return _exam_status(service, user.id, course_id, user.timezone)


@router.put(
    "/courses/{course_id}/exam",
    response_model=ExamStatusRead,
    responses=_RESPONSES,
    summary="Set, change or clear the exam date",
)
def set_exam_date(
    service: ExamServiceDep,
    user: CurrentUser,
    course_id: uuid.UUID,
    payload: ExamDateUpdate,
) -> ExamStatusRead:
    """A null date clears it. Exam mode is opt-in per course."""
    service.set_exam_date(user.id, course_id, payload.exam_date)
    return _exam_status(service, user.id, course_id, user.timezone)


def _exam_status(
    service: ExamServiceDep,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    timezone: str | None = None,
) -> ExamStatusRead:
    status_ = service.status(user_id, course_id, timezone=timezone)
    breakdown = status_.readiness

    return ExamStatusRead(
        exam_date=status_.exam_date,
        days_remaining=status_.days_remaining,
        has_passed=status_.has_passed,
        readiness=ReadinessRead(
            readiness=round(breakdown.readiness, 1),
            mean_effective_mastery=breakdown.mean_effective_mastery,
            coverage=breakdown.coverage,
            review_currency=breakdown.review_currency,
            topics_total=breakdown.topics_total,
            topics_started=breakdown.topics_started,
            overdue_cards=breakdown.overdue_cards,
            total_cards=breakdown.total_cards,
        ),
        topics_needing_attention=status_.topics_needing_attention,
    )
