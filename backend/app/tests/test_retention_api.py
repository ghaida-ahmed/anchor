"""Retention through the API: history, reviews, due queue, exam mode, isolation."""

import io
import uuid as uuid_module
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MasteryEvent, TopicMastery
from app.tests.conftest import auth, make_topic, quiz_payload

NOTES = (
    b"TCP provides reliable delivery using sequence numbers and acknowledgements. "
    b"On detecting packet loss the congestion window is halved, draining the "
    b"bottleneck queue. Additive increase then probes for capacity again."
)
DESCRIPTION = (
    "Reliable delivery using sequence numbers and acknowledgements, and halving "
    "the congestion window on packet loss."
)


def seed(client: TestClient, token: str, course_id: str, session: Session):
    from app.models import Topic

    existing = session.scalar(
        select(Topic).where(
            Topic.course_id == course_id,
            Topic.normalised_name == "tcp congestion control",
        )
    )
    if existing is None:
        client.post(
            f"/api/v1/courses/{course_id}/documents",
            files={"file": ("notes.txt", io.BytesIO(NOTES), "text/plain")},
            headers=auth(token),
        )
        existing = make_topic(session, course_id, "TCP Congestion Control", DESCRIPTION)
        session.flush()
    return existing


def take_quiz(client, token, course_id, session, llm, count=3, correct=True):
    """Generate, take and complete a quiz. Returns the attempt summary."""
    from app.models import QuizQuestion

    seed(client, token, course_id, session)
    llm.json_response = quiz_payload(count)
    quiz = client.post(
        f"/api/v1/courses/{course_id}/quizzes",
        json={"mode": "standard", "question_count": count},
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

    return client.post(
        f"/api/v1/attempts/{attempt['id']}/complete", headers=auth(token)
    ).json()


def make_cards(client, token, course_id, session, llm, count=3):
    topic = seed(client, token, course_id, session)
    llm.json_response = {
        "cards": [
            {"front": f"Front {i}", "back": f"Back {i}", "excerpt_number": 1}
            for i in range(count)
        ]
    }
    response = client.post(
        f"/api/v1/courses/{course_id}/flashcards",
        json={"topic_ids": [str(topic.id)]},
        headers=auth(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestMasteryHistory:
    def test_one_event_per_answer(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        take_quiz(client, token, course_id, session, llm, count=3)

        history = client.get(
            f"/api/v1/courses/{course_id}/mastery/history", headers=auth(token)
        ).json()

        assert len(history) == 3
        assert all(item["source_type"] == "quiz_answer" for item in history)

    def test_events_record_the_transition(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        take_quiz(client, token, course_id, session, llm, count=3)

        history = client.get(
            f"/api/v1/courses/{course_id}/mastery/history", headers=auth(token)
        ).json()

        assert history[0]["previous_mastery"] == 0.0
        assert history[0]["new_mastery"] > 0.0
        # Each event picks up where the previous one left off.
        for earlier, later in zip(history, history[1:], strict=False):
            assert later["previous_mastery"] == earlier["new_mastery"]

    def test_history_is_ordered_oldest_first(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        take_quiz(client, token, course_id, session, llm, count=3)

        history = client.get(
            f"/api/v1/courses/{course_id}/mastery/history", headers=auth(token)
        ).json()

        timestamps = [item["created_at"] for item in history]
        assert timestamps == sorted(timestamps)

    def test_history_is_immutable_under_later_activity(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        """Old rows must never be rewritten by newer evidence."""
        take_quiz(client, token, course_id, session, llm, count=3)
        before = client.get(
            f"/api/v1/courses/{course_id}/mastery/history", headers=auth(token)
        ).json()

        take_quiz(client, token, course_id, session, llm, count=3, correct=False)
        after = client.get(
            f"/api/v1/courses/{course_id}/mastery/history", headers=auth(token)
        ).json()

        assert after[: len(before)] == before

    def test_flashcard_reviews_create_their_own_events(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        cards = make_cards(client, token, course_id, session, llm, count=1)
        client.post(
            f"/api/v1/flashcards/{cards[0]['id']}/reviews",
            json={"rating": "good"},
            headers=auth(token),
        )

        history = client.get(
            f"/api/v1/courses/{course_id}/mastery/history", headers=auth(token)
        ).json()

        assert any(item["source_type"] == "flashcard_review" for item in history)


class TestReviewFlow:
    def test_reviewing_schedules_the_next_visit(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        cards = make_cards(client, token, course_id, session, llm, count=1)

        result = client.post(
            f"/api/v1/flashcards/{cards[0]['id']}/reviews",
            json={"rating": "good"},
            headers=auth(token),
        )

        assert result.status_code == 201
        body = result.json()
        assert body["interval_days"] == 1
        assert body["next_review_label"] == "tomorrow"
        assert body["due_at"] is not None

    def test_new_cards_are_due(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        make_cards(client, token, course_id, session, llm, count=3)

        summary = client.get(
            f"/api/v1/courses/{course_id}/flashcards/due", headers=auth(token)
        ).json()

        assert summary["total"] == 3
        assert summary["due_now"] == 3
        assert summary["never_reviewed"] == 3
        assert summary["overdue"] == 0

    def test_reviewed_cards_leave_the_due_queue(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        cards = make_cards(client, token, course_id, session, llm, count=2)
        for card in cards:
            client.post(
                f"/api/v1/flashcards/{card['id']}/reviews",
                json={"rating": "good"},
                headers=auth(token),
            )

        summary = client.get(
            f"/api/v1/courses/{course_id}/flashcards/due", headers=auth(token)
        ).json()

        assert summary["due_now"] == 0
        assert summary["upcoming"] == 2

    def test_again_keeps_the_card_due(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        cards = make_cards(client, token, course_id, session, llm, count=1)

        result = client.post(
            f"/api/v1/flashcards/{cards[0]['id']}/reviews",
            json={"rating": "again"},
            headers=auth(token),
        ).json()

        assert result["interval_days"] == 0
        assert result["next_review_label"] == "in a few minutes"

    def test_reviews_update_mastery_at_reduced_weight(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        cards = make_cards(client, token, course_id, session, llm, count=1)
        client.post(
            f"/api/v1/flashcards/{cards[0]['id']}/reviews",
            json={"rating": "good"},
            headers=auth(token),
        )

        session.expire_all()
        row = session.scalar(select(TopicMastery))
        assert row is not None
        assert row.flashcard_reviews == 1
        # Quiz question count is untouched: self-reported recall is not a question.
        assert row.questions_attempted == 0
        assert row.mastery_score > 0

    def test_hard_is_neutral_for_mastery(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        cards = make_cards(client, token, course_id, session, llm, count=1)
        client.post(
            f"/api/v1/flashcards/{cards[0]['id']}/reviews",
            json={"rating": "hard"},
            headers=auth(token),
        )

        session.expire_all()
        row = session.scalar(select(TopicMastery))
        assert row.raw_score == 0.0
        assert row.flashcard_reviews == 1

    def test_repeated_easy_cannot_reach_full_mastery(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        """The safeguard against grinding Easy to fake mastery."""
        from app.services.learning.mastery import FLASHCARD_RAW_CEILING

        cards = make_cards(client, token, course_id, session, llm, count=1)
        for _ in range(30):
            client.post(
                f"/api/v1/flashcards/{cards[0]['id']}/reviews",
                json={"rating": "easy"},
                headers=auth(token),
            )

        session.expire_all()
        row = session.scalar(select(TopicMastery))
        assert row.raw_score <= FLASHCARD_RAW_CEILING


class TestExamMode:
    def test_no_exam_date_by_default(
        self, client: TestClient, token: str, course_id: str
    ) -> None:
        body = client.get(f"/api/v1/courses/{course_id}/exam", headers=auth(token)).json()

        assert body["exam_date"] is None
        assert body["days_remaining"] is None
        assert body["has_passed"] is False

    def test_setting_and_clearing_the_date(
        self, client: TestClient, token: str, course_id: str
    ) -> None:
        future = (datetime.now(UTC).date() + timedelta(days=20)).isoformat()

        set_response = client.put(
            f"/api/v1/courses/{course_id}/exam",
            json={"exam_date": future},
            headers=auth(token),
        ).json()
        assert set_response["exam_date"] == future
        assert set_response["days_remaining"] == 20

        cleared = client.put(
            f"/api/v1/courses/{course_id}/exam",
            json={"exam_date": None},
            headers=auth(token),
        ).json()
        assert cleared["exam_date"] is None

    def test_a_past_exam_is_handled_gracefully(
        self, client: TestClient, token: str, course_id: str
    ) -> None:
        past = (datetime.now(UTC).date() - timedelta(days=3)).isoformat()

        body = client.put(
            f"/api/v1/courses/{course_id}/exam",
            json={"exam_date": past},
            headers=auth(token),
        ).json()

        assert body["has_passed"] is True
        assert body["days_remaining"] == -3

    def test_readiness_is_zero_before_any_practice(
        self, client: TestClient, token: str, course_id: str, session: Session
    ) -> None:
        make_topic(session, course_id, "Untouched")
        session.flush()

        body = client.get(f"/api/v1/courses/{course_id}/exam", headers=auth(token)).json()

        assert body["readiness"]["readiness"] == 0.0
        assert body["readiness"]["coverage"] == 0.0

    def test_unpracticed_topics_hold_readiness_down(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        take_quiz(client, token, course_id, session, llm, count=3)
        for name in ("Untouched A", "Untouched B", "Untouched C"):
            make_topic(session, course_id, name)
        session.flush()

        body = client.get(f"/api/v1/courses/{course_id}/exam", headers=auth(token)).json()

        assert body["readiness"]["coverage"] < 0.5
        assert body["readiness"]["readiness"] < 50

    def test_exam_mode_generates_a_grounded_quiz(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        seed(client, token, course_id, session)
        client.put(
            f"/api/v1/courses/{course_id}/exam",
            json={
                "exam_date": (datetime.now(UTC).date() + timedelta(days=5)).isoformat()
            },
            headers=auth(token),
        )
        llm.json_response = quiz_payload(3)

        response = client.post(
            f"/api/v1/courses/{course_id}/quizzes",
            json={"mode": "exam", "question_count": 3},
            headers=auth(token),
        )

        assert response.status_code == 201
        body = response.json()
        assert body["mode"] == "exam"
        assert "exam" in body["selection_rationale"].lower()


class TestAnalytics:
    def test_empty_course_returns_empty_series(
        self, client: TestClient, token: str, course_id: str
    ) -> None:
        body = client.get(
            f"/api/v1/courses/{course_id}/analytics", headers=auth(token)
        ).json()

        assert body["daily"] == []
        assert body["total_events"] == 0
        assert body["most_improved_topic"] is None

    def test_activity_produces_one_bucket_per_active_day(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        take_quiz(client, token, course_id, session, llm, count=3)

        body = client.get(
            f"/api/v1/courses/{course_id}/analytics", headers=auth(token)
        ).json()

        assert body["active_days"] == 1
        assert len(body["daily"]) == 1
        assert body["daily"][0]["answers"] == 3
        assert body["total_events"] == 3

    def test_idle_days_are_absent_not_zeroed(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        """Drawing a zero for an idle day would imply practice that did not happen."""
        take_quiz(client, token, course_id, session, llm, count=3)

        body = client.get(
            f"/api/v1/courses/{course_id}/analytics", headers=auth(token)
        ).json()

        assert all(point["answers"] > 0 for point in body["daily"])

    def test_attempt_scores_are_oldest_first(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        take_quiz(client, token, course_id, session, llm, count=3, correct=False)
        take_quiz(client, token, course_id, session, llm, count=3, correct=True)

        body = client.get(
            f"/api/v1/courses/{course_id}/analytics", headers=auth(token)
        ).json()

        scores = body["attempt_scores"]
        assert len(scores) == 2
        assert [s["completed_at"] for s in scores] == sorted(
            s["completed_at"] for s in scores
        )


class TestIsolation:
    def test_cannot_read_another_users_history(
        self, client: TestClient, other_token: str, course_id: str
    ) -> None:
        assert (
            client.get(
                f"/api/v1/courses/{course_id}/mastery/history", headers=auth(other_token)
            ).status_code
            == 404
        )

    def test_cannot_read_another_users_analytics(
        self, client: TestClient, other_token: str, course_id: str
    ) -> None:
        assert (
            client.get(
                f"/api/v1/courses/{course_id}/analytics", headers=auth(other_token)
            ).status_code
            == 404
        )

    def test_cannot_read_another_users_due_queue(
        self, client: TestClient, other_token: str, course_id: str
    ) -> None:
        assert (
            client.get(
                f"/api/v1/courses/{course_id}/flashcards/due", headers=auth(other_token)
            ).status_code
            == 404
        )

    def test_cannot_review_another_users_card(
        self,
        client: TestClient,
        token: str,
        other_token: str,
        course_id: str,
        session: Session,
        llm,
    ) -> None:
        cards = make_cards(client, token, course_id, session, llm, count=1)

        response = client.post(
            f"/api/v1/flashcards/{cards[0]['id']}/reviews",
            json={"rating": "good"},
            headers=auth(other_token),
        )

        assert response.status_code == 404

    def test_cannot_read_or_set_another_users_exam_date(
        self, client: TestClient, other_token: str, course_id: str
    ) -> None:
        assert (
            client.get(
                f"/api/v1/courses/{course_id}/exam", headers=auth(other_token)
            ).status_code
            == 404
        )
        assert (
            client.put(
                f"/api/v1/courses/{course_id}/exam",
                json={"exam_date": "2030-01-01"},
                headers=auth(other_token),
            ).status_code
            == 404
        )

    def test_cannot_start_an_exam_quiz_in_another_users_course(
        self, client: TestClient, other_token: str, course_id: str, llm
    ) -> None:
        response = client.post(
            f"/api/v1/courses/{course_id}/quizzes",
            json={"mode": "exam", "question_count": 3},
            headers=auth(other_token),
        )

        assert response.status_code == 404
        assert llm.json_call_count == 0

    def test_history_is_scoped_per_user(
        self,
        client: TestClient,
        token: str,
        other_token: str,
        course_id: str,
        session: Session,
        llm,
    ) -> None:
        take_quiz(client, token, course_id, session, llm, count=3)

        session.expire_all()
        rows = session.scalars(select(MasteryEvent)).all()
        owners = {row.user_id for row in rows}
        assert len(owners) == 1

    def test_retention_endpoints_require_authentication(
        self, client: TestClient, course_id: str
    ) -> None:
        card_id = uuid_module.uuid4()
        assert (
            client.get(f"/api/v1/courses/{course_id}/mastery/history").status_code == 401
        )
        assert client.get(f"/api/v1/courses/{course_id}/analytics").status_code == 401
        assert (
            client.get(f"/api/v1/courses/{course_id}/flashcards/due").status_code == 401
        )
        assert client.get(f"/api/v1/courses/{course_id}/exam").status_code == 401
        assert (
            client.post(
                f"/api/v1/flashcards/{card_id}/reviews", json={"rating": "good"}
            ).status_code
            == 401
        )
