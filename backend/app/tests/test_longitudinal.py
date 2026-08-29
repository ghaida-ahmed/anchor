"""A 60-day timeline, driven by the injectable clock.

Waiting sixty real days is obviously not an option, and monkey-patching
`datetime.now` across the codebase would be both fragile and untestable in itself.
Instead every wall-clock read goes through `app.core.clock.now`, and this module
steps that clock forward.

The timeline mirrors a real student:

    Day 0   learns a topic, answers a quiz, reviews cards
    Day 3   some cards fall due; the estimate has barely moved
    Day 14  reviews the due cards; history and scheduling stay consistent
    Day 30  an untouched topic's estimate has dropped and the selector notices
    Day 60  a strong but abandoned topic resurfaces for practice
"""

import io
import uuid as uuid_module
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import frozen_time
from app.models import MasteryEvent, QuizQuestion, TopicMastery
from app.services.learning.adaptive import priority_for, select_topics
from app.services.learning.mastery_service import MasteryService
from app.services.learning.retention import effective_mastery
from app.tests.conftest import auth, make_topic, quiz_payload

DAY_0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)

NOTES = (
    b"TCP provides reliable delivery using sequence numbers and acknowledgements. "
    b"On detecting packet loss the congestion window is halved, draining the "
    b"bottleneck queue. Additive increase then probes for capacity again."
)
DESCRIPTION = (
    "Reliable delivery using sequence numbers and acknowledgements, and halving "
    "the congestion window on packet loss."
)


def day(offset: float) -> datetime:
    return DAY_0 + timedelta(days=offset)


def answer_whole_quiz(client, token, course_id, session, llm, *, correct: bool):
    llm.json_response = quiz_payload(3)
    quiz = client.post(
        f"/api/v1/courses/{course_id}/quizzes",
        json={"mode": "standard", "question_count": 3},
        headers=auth(token),
    ).json()

    key = {
        str(q.id): q.correct_index
        for q in session.scalars(
            select(QuizQuestion).where(QuizQuestion.quiz_id == quiz["id"])
        )
    }
    attempt = client.post(
        f"/api/v1/quizzes/{quiz['id']}/attempts", headers=auth(token)
    ).json()

    for question in quiz["questions"]:
        choice = key[question["id"]] if correct else (key[question["id"]] + 1) % 4
        client.post(
            f"/api/v1/attempts/{attempt['id']}/answers",
            json={"question_id": question["id"], "selected_index": choice},
            headers=auth(token),
        )
    client.post(f"/api/v1/attempts/{attempt['id']}/complete", headers=auth(token))
    return quiz


def test_sixty_day_learning_timeline(
    client: TestClient, token: str, course_id: str, session: Session, llm, embeddings
) -> None:
    me = client.get("/api/v1/auth/me", headers=auth(token)).json()
    user_id = uuid_module.UUID(me["id"])
    mastery_service = MasteryService(session)

    # ---------------------------------------------------------------- Day 0 ---
    with frozen_time(DAY_0):
        client.post(
            f"/api/v1/courses/{course_id}/documents",
            files={"file": ("notes.txt", io.BytesIO(NOTES), "text/plain")},
            headers=auth(token),
        )
        topic = make_topic(session, course_id, "TCP Congestion Control", DESCRIPTION)
        session.flush()

        answer_whole_quiz(client, token, course_id, session, llm, correct=True)

        llm.json_response = {
            "cards": [
                {"front": f"Front {i}", "back": f"Back {i}", "excerpt_number": 1}
                for i in range(3)
            ]
        }
        cards = client.post(
            f"/api/v1/courses/{course_id}/flashcards",
            json={"topic_ids": [str(topic.id)]},
            headers=auth(token),
        ).json()

        for card in cards:
            client.post(
                f"/api/v1/flashcards/{card['id']}/reviews",
                json={"rating": "good"},
                headers=auth(token),
            )

        session.expire_all()
        row = session.scalar(select(TopicMastery))
        assert row is not None
        stored_day0 = row.mastery_score
        assert stored_day0 > 0
        assert row.questions_attempted == 3
        assert row.flashcard_reviews == 3

        due = client.get(
            f"/api/v1/courses/{course_id}/flashcards/due", headers=auth(token)
        ).json()
        assert due["due_now"] == 0, "all three cards were just reviewed"

    # ---------------------------------------------------------------- Day 3 ---
    with frozen_time(day(3)):
        # Cards reviewed with Good on day 0 had a 1-day interval, so they are due.
        due = client.get(
            f"/api/v1/courses/{course_id}/flashcards/due", headers=auth(token)
        ).json()
        assert due["due_now"] == 3
        assert due["overdue"] == 3, "due more than a day ago"

        session.expire_all()
        row = session.scalar(select(TopicMastery))
        estimate = effective_mastery(
            row.mastery_score,
            row.questions_attempted + 0.4 * row.flashcard_reviews,
            row.last_practised_at,
            at=day(3),
        )
        assert row.mastery_score == stored_day0, "stored evidence is untouched"
        assert estimate < stored_day0, "the estimate has begun to soften"
        assert estimate > stored_day0 * 0.9, "three days should barely matter"

    # --------------------------------------------------------------- Day 14 ---
    with frozen_time(day(14)):
        events_before = len(session.scalars(select(MasteryEvent)).all())

        for card in cards:
            result = client.post(
                f"/api/v1/flashcards/{card['id']}/reviews",
                json={"rating": "good"},
                headers=auth(token),
            ).json()
            # Overdue credit: reviewed 14 days late on a 1-day interval, bounded
            # at twice the previous interval, so the next interval grows.
            assert result["interval_days"] >= 3

        session.expire_all()
        events_after = len(session.scalars(select(MasteryEvent)).all())
        assert events_after == events_before + 3, "one event per review, no more"

        due = client.get(
            f"/api/v1/courses/{course_id}/flashcards/due", headers=auth(token)
        ).json()
        assert due["due_now"] == 0

    # --------------------------------------------------------------- Day 30 ---
    with frozen_time(day(30)):
        neglected = make_topic(session, course_id, "Neglected Topic", DESCRIPTION)
        session.flush()
        # Give it strong but old evidence.
        session.add(
            TopicMastery(
                user_id=user_id,
                course_id=uuid_module.UUID(course_id),
                topic_id=neglected.id,
                raw_score=85.0,
                mastery_score=85.0,
                questions_attempted=10,
                correct_answers=9,
                last_answer_correct=True,
                last_practised_at=DAY_0,
            )
        )
        session.flush()

        candidates = {
            c.name: c
            for c in mastery_service.candidates_for(user_id, course_id, at=day(30))
        }
        stale = candidates["Neglected Topic"]

        assert stale.state.mastery_score == 85.0, "stored value never changed"
        assert stale.effective_mastery < 85.0, "but the estimate has decayed"
        assert stale.effective_band in ("developing", "strong")

        mastery = client.get(
            f"/api/v1/courses/{course_id}/mastery", headers=auth(token)
        ).json()
        entry = next(t for t in mastery["topics"] if t["topic_name"] == "Neglected Topic")
        assert entry["mastery_score"] == 85.0
        assert entry["effective_mastery"] < 85.0
        assert entry["days_since_practice"] == 30.0
        assert entry["retention_status"] in ("review_soon", "due", "overdue")

    # --------------------------------------------------------------- Day 60 ---
    with frozen_time(day(60)):
        candidates = mastery_service.candidates_for(user_id, course_id, at=day(60))
        by_name = {c.name: c for c in candidates}

        abandoned = by_name["Neglected Topic"]
        at_30 = effective_mastery(85.0, 10, DAY_0, at=day(30))
        at_60 = effective_mastery(85.0, 10, DAY_0, at=day(60))
        assert at_60 < at_30, "the estimate keeps softening"
        assert at_60 > 85.0 * 0.5, "but neglect never erases the evidence"

        # The selector must now surface the abandoned topic.
        selected = select_topics(candidates, question_count=6)
        assert any(item.name == "Neglected Topic" for item in selected)

        # And its priority must have risen purely through elapsed time.
        priority_now = priority_for(abandoned)
        fresh_equivalent = priority_for(
            type(abandoned)(
                topic_id=abandoned.topic_id,
                name=abandoned.name,
                state=abandoned.state,
                effective_mastery=85.0,
                due_cards=0,
            )
        )
        assert priority_now > fresh_equivalent

    # ------------------------------------------------------------ Invariants ---
    session.expire_all()
    rows = session.scalars(select(TopicMastery)).all()
    assert all(0 <= row.mastery_score <= 100 for row in rows)
    assert all(row.correct_answers <= row.questions_attempted for row in rows)

    history = client.get(
        f"/api/v1/courses/{course_id}/mastery/history", headers=auth(token)
    ).json()
    timestamps = [item["created_at"] for item in history]
    assert timestamps == sorted(timestamps), "history stays ordered across the timeline"
