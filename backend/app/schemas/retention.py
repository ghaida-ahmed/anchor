"""Contracts for retention, review scheduling, analytics and exam preparation."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models import ReviewRating
from app.schemas.common import ORMModel

# --- Mastery with time ---------------------------------------------------------


class TopicRetentionRead(BaseModel):
    """A topic's mastery, with the time dimension made explicit.

    `mastery_score` is what the student demonstrated and never changes on its own.
    `effective_mastery` is the present estimate after the decay heuristic. Showing
    both is deliberate: a drop should read as "worth reviewing", not as evidence
    being taken away.
    """

    topic_id: uuid.UUID
    topic_name: str
    mastery_score: float
    effective_mastery: float
    band: str
    band_label: str
    effective_band: str
    retention_status: str
    retention_label: str
    questions_attempted: int
    correct_answers: int
    flashcard_reviews: int
    accuracy: float | None
    days_since_practice: float | None
    last_practised_at: datetime | None
    due_cards: int


class CourseMasteryRead(BaseModel):
    course_id: uuid.UUID
    topics: list[TopicRetentionRead]
    # Mean effective mastery across ALL active topics, counting never-started ones
    # as zero. This is the honest headline: breadth counts.
    course_mastery: float
    # Mean across started topics only — "how well you know what you have studied".
    practised_mastery: float | None
    coverage: float
    topics_total: int
    topics_started: int
    topics_strong: int
    questions_answered: int
    correct_answers: int
    accuracy: float | None
    strongest_topic: str | None
    weakest_topic: str | None
    needs_review_topic: str | None


class MasteryEventRead(BaseModel):
    id: uuid.UUID
    topic_id: uuid.UUID
    topic_name: str
    source_type: str
    previous_mastery: float
    new_mastery: float
    effective_mastery_at_event: float
    was_correct: bool | None
    difficulty: str | None
    created_at: datetime


# --- Analytics -----------------------------------------------------------------


class DailyActivityRead(BaseModel):
    """One day on which something happened. Idle days are absent, not zeroed."""

    day: date
    answers: int
    correct: int
    mean_mastery: float


class AttemptScoreRead(BaseModel):
    completed_at: datetime
    score_percent: float


class TopicTrendRead(BaseModel):
    topic_id: uuid.UUID
    topic_name: str
    first_mastery: float
    latest_mastery: float
    change: float


class CourseAnalyticsRead(BaseModel):
    daily: list[DailyActivityRead]
    attempt_scores: list[AttemptScoreRead]
    topic_trends: list[TopicTrendRead]
    most_improved_topic: str | None
    total_events: int
    active_days: int
    first_activity: datetime | None
    last_activity: datetime | None


# --- Flashcard review ----------------------------------------------------------


class DueSummaryRead(BaseModel):
    due_now: int
    overdue: int
    upcoming: int
    total: int
    never_reviewed: int


class ReviewStateRead(BaseModel):
    interval_days: int
    review_count: int
    success_count: int
    lapses: int
    last_reviewed_at: datetime | None
    due_at: datetime | None
    is_due: bool


class ReviewSubmit(BaseModel):
    rating: ReviewRating


class ReviewResultRead(BaseModel):
    flashcard_id: uuid.UUID
    # Student-facing wording, e.g. "in 3 days". Scheduling internals stay internal.
    next_review_label: str
    due_at: datetime | None
    interval_days: int


# --- Exam preparation ----------------------------------------------------------


class ExamDateUpdate(BaseModel):
    # Null clears the date. Exam mode is optional per course by design.
    exam_date: date | None = None


class ReadinessRead(BaseModel):
    readiness: float
    mean_effective_mastery: float
    coverage: float
    review_currency: float
    topics_total: int
    topics_started: int
    overdue_cards: int
    total_cards: int


class ExamStatusRead(BaseModel):
    exam_date: date | None
    days_remaining: int | None
    has_passed: bool
    readiness: ReadinessRead
    topics_needing_attention: list[str]


class ExamPlanTopicRead(BaseModel):
    topic_id: uuid.UUID
    topic_name: str
    question_count: int
    priority: float
    band: str


class FlashcardWithStateRead(ORMModel):
    id: uuid.UUID
    course_id: uuid.UUID
    topic_id: uuid.UUID
    topic_name: str
    front: str
    back: str
    source: dict | None = Field(default=None)
    review: ReviewStateRead | None = None
    created_at: datetime
