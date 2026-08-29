"""Persisting mastery, and reading it back for the adaptive engine.

The algorithm itself is in `mastery.py` as pure functions; this module only moves
state in and out of the database.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import now
from app.core.exceptions import ResourceNotFoundError
from app.models import (
    AnswerVerdict,
    Course,
    Difficulty,
    MasteryEvent,
    MasteryEventSource,
    Topic,
    TopicMastery,
)
from app.services.learning import mastery as algorithm
from app.services.learning.adaptive import TopicCandidate
from app.services.learning.mastery import MasteryState
from app.services.learning.retention import effective_mastery


def state_of(row: TopicMastery | None) -> MasteryState:
    """Read a stored row as the algorithm's state, or the fresh-topic default."""
    if row is None:
        return algorithm.NEW_TOPIC
    return MasteryState(
        raw_score=row.raw_score,
        mastery_score=row.mastery_score,
        questions_attempted=row.questions_attempted,
        correct_answers=row.correct_answers,
        last_answer_correct=row.last_answer_correct,
        last_practised_at=row.last_practised_at,
        flashcard_reviews=row.flashcard_reviews,
    )


def effective_of(state: MasteryState, *, at: datetime | None = None) -> float:
    """Present estimate for a stored state."""
    return effective_mastery(
        state.mastery_score, state.evidence, state.last_practised_at, at=at
    )


class MasteryService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record_answer(
        self,
        *,
        user_id: uuid.UUID,
        course_id: uuid.UUID,
        topic_id: uuid.UUID,
        difficulty: Difficulty,
        correct: bool,
        answered_at: datetime | None = None,
        source_id: uuid.UUID | None = None,
    ) -> TopicMastery:
        """Fold one quiz answer into the student's mastery of a topic.

        Called once per answer rather than once per quiz, so an abandoned attempt
        still credits the questions that were actually answered. Writes exactly one
        `MasteryEvent`.
        """
        moment = answered_at or now()
        row, previous = self._load(user_id, course_id, topic_id)

        updated = algorithm.apply_answer(
            previous, difficulty=difficulty, correct=correct, answered_at=moment
        )

        self._write(row, updated)
        self._record_event(
            row,
            previous=previous,
            updated=updated,
            source_type=MasteryEventSource.QUIZ_ANSWER,
            source_id=source_id,
            was_correct=correct,
            difficulty=difficulty,
            at=moment,
        )
        return row

    def record_short_answer(
        self,
        *,
        user_id: uuid.UUID,
        course_id: uuid.UUID,
        topic_id: uuid.UUID,
        difficulty: Difficulty,
        verdict: AnswerVerdict,
        answered_at: datetime | None = None,
        source_id: uuid.UUID | None = None,
    ) -> TopicMastery | None:
        """Fold one graded short answer into the student's mastery of a topic.

        Returns None and writes nothing at all for an `uncertain` verdict. The
        caller is expected to filter those out too, but this is the layer that
        owns the student's record, so it enforces the rule itself rather than
        trusting every caller to remember.

        The event's `source_type` stays QUIZ_ANSWER — a short answer *is* a quiz
        answer, and `source_id` points at the row carrying the verdict, so nothing
        about the audit trail is lost by not minting a new source kind.
        `was_correct` is None for a partial answer: it was neither.
        """
        if verdict is AnswerVerdict.UNCERTAIN:
            return None

        moment = answered_at or now()
        row, previous = self._load(user_id, course_id, topic_id)

        updated = algorithm.apply_short_answer(
            previous,
            difficulty=difficulty,
            verdict=verdict.value,
            answered_at=moment,
        )
        if updated is previous:
            return None

        was_correct: bool | None = None
        if verdict is AnswerVerdict.CORRECT:
            was_correct = True
        elif verdict is AnswerVerdict.INCORRECT:
            was_correct = False

        self._write(row, updated)
        self._record_event(
            row,
            previous=previous,
            updated=updated,
            source_type=MasteryEventSource.QUIZ_ANSWER,
            source_id=source_id,
            was_correct=was_correct,
            difficulty=difficulty,
            at=moment,
        )
        return row

    def record_flashcard_review(
        self,
        *,
        user_id: uuid.UUID,
        course_id: uuid.UUID,
        topic_id: uuid.UUID,
        rating: str,
        reviewed_at: datetime | None = None,
        source_id: uuid.UUID | None = None,
    ) -> TopicMastery:
        """Fold one flashcard rating into mastery, at reduced weight.

        See `mastery.apply_flashcard_review` for the weighting and the ceiling that
        stops repeated Easy ratings from standing in for demonstrated mastery.
        """
        moment = reviewed_at or now()
        row, previous = self._load(user_id, course_id, topic_id)

        updated = algorithm.apply_flashcard_review(
            previous, rating=rating, reviewed_at=moment
        )

        self._write(row, updated)
        self._record_event(
            row,
            previous=previous,
            updated=updated,
            source_type=MasteryEventSource.FLASHCARD_REVIEW,
            source_id=source_id,
            was_correct=None if rating == "hard" else rating != "again",
            difficulty=None,
            at=moment,
        )
        return row

    def history_for_course(
        self, user_id: uuid.UUID, course_id: uuid.UUID, *, limit: int = 500
    ) -> list[MasteryEvent]:
        """Mastery-changing events, oldest first, for charting a trend."""
        self._assert_course_owned(user_id, course_id)
        return list(
            self.session.scalars(
                select(MasteryEvent)
                .where(
                    MasteryEvent.user_id == user_id,
                    MasteryEvent.course_id == course_id,
                )
                .order_by(MasteryEvent.created_at)
                .limit(limit)
            )
        )

    def _load(
        self, user_id: uuid.UUID, course_id: uuid.UUID, topic_id: uuid.UUID
    ) -> tuple[TopicMastery, MasteryState]:
        row = self.session.scalar(
            select(TopicMastery).where(
                TopicMastery.user_id == user_id, TopicMastery.topic_id == topic_id
            )
        )
        if row is None:
            row = TopicMastery(user_id=user_id, course_id=course_id, topic_id=topic_id)
            self.session.add(row)
            self.session.flush()
        return row, state_of(row)

    @staticmethod
    def _write(row: TopicMastery, updated: MasteryState) -> None:
        row.raw_score = updated.raw_score
        row.mastery_score = updated.mastery_score
        row.questions_attempted = updated.questions_attempted
        row.correct_answers = updated.correct_answers
        row.last_answer_correct = updated.last_answer_correct
        row.last_practised_at = updated.last_practised_at
        row.flashcard_reviews = updated.flashcard_reviews

    def _record_event(
        self,
        row: TopicMastery,
        *,
        previous: MasteryState,
        updated: MasteryState,
        source_type: MasteryEventSource,
        source_id: uuid.UUID | None,
        was_correct: bool | None,
        difficulty: Difficulty | None,
        at: datetime,
    ) -> None:
        """Append one immutable history row.

        `effective_mastery_at_event` is frozen here rather than recomputed on read,
        so changing the decay heuristic later cannot rewrite what a student was
        shown last month.
        """
        self.session.add(
            MasteryEvent(
                user_id=row.user_id,
                course_id=row.course_id,
                topic_id=row.topic_id,
                source_type=source_type,
                source_id=source_id,
                previous_raw_score=previous.raw_score,
                new_raw_score=updated.raw_score,
                previous_mastery=previous.mastery_score,
                new_mastery=updated.mastery_score,
                effective_mastery_at_event=effective_mastery(
                    updated.mastery_score,
                    updated.evidence,
                    updated.last_practised_at,
                    at=at,
                ),
                was_correct=was_correct,
                difficulty=difficulty,
                questions_attempted_after=updated.questions_attempted,
            )
        )

    def for_course(
        self, user_id: uuid.UUID, course_id: uuid.UUID
    ) -> list[tuple[Topic, MasteryState]]:
        """Every active topic in the course with the student's mastery of it.

        A LEFT JOIN, so topics the student has never attempted come back with the
        fresh-topic state rather than being missing — "not started" is a real state
        the dashboard must show.
        """
        self._assert_course_owned(user_id, course_id)

        rows = self.session.execute(
            select(Topic, TopicMastery)
            .outerjoin(
                TopicMastery,
                (TopicMastery.topic_id == Topic.id) & (TopicMastery.user_id == user_id),
            )
            .where(Topic.course_id == course_id, Topic.is_active.is_(True))
            .order_by(Topic.name)
        ).all()

        return [(topic, state_of(row)) for topic, row in rows]

    def candidates_for(
        self,
        user_id: uuid.UUID,
        course_id: uuid.UUID,
        *,
        at: datetime | None = None,
        due_by_topic: dict[uuid.UUID, int] | None = None,
    ) -> list[TopicCandidate]:
        """The adaptive engine's view of the course, with time already applied.

        Effective mastery is computed here rather than inside the selector so the
        selector stays a pure function and can be tested at any instant.
        """
        due = due_by_topic or {}
        return [
            TopicCandidate(
                topic_id=topic.id,
                name=topic.name,
                state=state,
                effective_mastery=effective_mastery(
                    state.mastery_score, state.evidence, state.last_practised_at, at=at
                ),
                due_cards=due.get(topic.id, 0),
            )
            for topic, state in self.for_course(user_id, course_id)
        ]

    def _assert_course_owned(self, user_id: uuid.UUID, course_id: uuid.UUID) -> None:
        owned = self.session.scalar(
            select(Course.id).where(Course.id == course_id, Course.user_id == user_id)
        )
        if owned is None:
            raise ResourceNotFoundError("Course", str(course_id))
