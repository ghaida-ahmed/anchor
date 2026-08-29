"""Adaptive quiz generation against real mastery, plus grounded flashcards."""

import io

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Flashcard, Topic, TopicMastery
from app.tests.conftest import auth, make_topic

NOTES = (
    b"TCP provides reliable delivery using sequence numbers and acknowledgements. "
    b"On detecting packet loss the congestion window is halved, draining the "
    b"bottleneck queue. The Domain Name System resolves names into addresses by "
    b"querying root servers then authoritative servers, caching each answer."
)
DESCRIPTIONS = {
    "TCP Congestion Control": (
        "Reliable delivery using sequence numbers and acknowledgements, and halving "
        "the congestion window on packet loss."
    ),
    "DNS Resolution": (
        "The Domain Name System resolves names into addresses by querying root "
        "servers then authoritative servers, caching each answer."
    ),
}


def seed_course(client, token, course_id, session) -> dict[str, Topic]:
    client.post(
        f"/api/v1/courses/{course_id}/documents",
        files={"file": ("notes.txt", io.BytesIO(NOTES), "text/plain")},
        headers=auth(token),
    )
    topics = {
        name: make_topic(session, course_id, name, description)
        for name, description in DESCRIPTIONS.items()
    }
    session.flush()
    return topics


def flashcard_payload(count: int = 2) -> dict:
    return {
        "cards": [
            {
                "front": f"Prompt {index}",
                "back": f"Answer {index} drawn from the excerpt.",
                "excerpt_number": 1,
            }
            for index in range(count)
        ]
    }


def set_mastery(
    session: Session, user_id, course_id, topic: Topic, score: float, attempted: int
):
    row = TopicMastery(
        user_id=user_id,
        course_id=course_id,
        topic_id=topic.id,
        raw_score=score,
        mastery_score=score,
        questions_attempted=attempted,
        correct_answers=int(attempted * score / 100),
        last_answer_correct=score > 50,
    )
    session.add(row)
    session.flush()
    return row


class TestAdaptiveGeneration:
    def test_adaptive_mode_explains_its_selection(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        seed_course(client, token, course_id, session)
        llm.json_response = {
            "questions": [
                {
                    "question_text": "Grounded question?",
                    "options": ["A", "B", "C", "D"],
                    "correct_index": 1,
                    "explanation": "From the excerpt.",
                    "difficulty": "easy",
                    "excerpt_number": 1,
                }
            ]
        }

        response = client.post(
            f"/api/v1/courses/{course_id}/quizzes",
            json={"mode": "adaptive", "question_count": 4},
            headers=auth(token),
        )

        assert response.status_code == 201
        body = response.json()
        assert body["mode"] == "adaptive"
        # Rationale is template-built, never generated.
        assert body["selection_rationale"]
        assert "Selected because" in body["selection_rationale"]

    def test_adaptive_mode_prioritises_the_weak_topic(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        topics = seed_course(client, token, course_id, session)
        me = client.get("/api/v1/auth/me", headers=auth(token)).json()
        import uuid as _uuid

        user_id = _uuid.UUID(me["id"])
        set_mastery(
            session, user_id, course_id, topics["TCP Congestion Control"], 92.0, 20
        )
        set_mastery(session, user_id, course_id, topics["DNS Resolution"], 15.0, 8)

        llm.json_response = {
            "questions": [
                {
                    "question_text": "Q?",
                    "options": ["A", "B", "C", "D"],
                    "correct_index": 0,
                    "explanation": "From the excerpt.",
                    "difficulty": "easy",
                    "excerpt_number": 1,
                }
            ]
        }

        body = client.post(
            f"/api/v1/courses/{course_id}/quizzes",
            json={"mode": "adaptive", "question_count": 4},
            headers=auth(token),
        ).json()

        assert "DNS Resolution" in body["selection_rationale"]
        # The first prompt sent to the model is for the highest-priority topic.
        assert "DNS Resolution" in llm.json_calls[0][-1].content

    def test_adaptive_mode_needs_topics(
        self, client: TestClient, token: str, course_id: str, llm
    ) -> None:
        response = client.post(
            f"/api/v1/courses/{course_id}/quizzes",
            json={"mode": "adaptive", "question_count": 4},
            headers=auth(token),
        )

        assert response.status_code == 400
        assert llm.json_call_count == 0


class TestRecommendations:
    def test_recommendations_need_no_model_call(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        """These load on every dashboard visit; a model call would be indefensible."""
        seed_course(client, token, course_id, session)

        response = client.get(
            f"/api/v1/courses/{course_id}/recommendations", headers=auth(token)
        )

        assert response.status_code == 200
        assert response.json()
        assert llm.json_call_count == 0
        assert llm.call_count == 0

    def test_recommendations_name_the_weak_topic(
        self, client: TestClient, token: str, course_id: str, session: Session
    ) -> None:
        topics = seed_course(client, token, course_id, session)
        import uuid as _uuid

        me = client.get("/api/v1/auth/me", headers=auth(token)).json()
        set_mastery(
            session, _uuid.UUID(me["id"]), course_id, topics["DNS Resolution"], 18.0, 9
        )

        body = client.get(
            f"/api/v1/courses/{course_id}/recommendations", headers=auth(token)
        ).json()

        assert any("DNS Resolution" in item["title"] for item in body)

    def test_a_course_without_topics_gets_a_useful_prompt(
        self, client: TestClient, token: str, course_id: str
    ) -> None:
        body = client.get(
            f"/api/v1/courses/{course_id}/recommendations", headers=auth(token)
        ).json()

        assert body[0]["kind"] == "no_topics"


class TestFlashcards:
    def test_generation_is_grounded_and_persisted(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        topics = seed_course(client, token, course_id, session)
        llm.json_response = flashcard_payload(2)

        response = client.post(
            f"/api/v1/courses/{course_id}/flashcards",
            json={"topic_ids": [str(topics["DNS Resolution"].id)]},
            headers=auth(token),
        )

        assert response.status_code == 201
        cards = response.json()
        assert cards
        for card in cards:
            assert card["front"] and card["back"]
            assert card["source"]["document_name"] == "notes.txt"
            assert card["source"]["page_number"] is None

    def test_listing_cards_makes_no_model_call(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        """Opening the tab must not regenerate; that would burn quota on a refresh."""
        topics = seed_course(client, token, course_id, session)
        llm.json_response = flashcard_payload(2)
        client.post(
            f"/api/v1/courses/{course_id}/flashcards",
            json={"topic_ids": [str(topics["DNS Resolution"].id)]},
            headers=auth(token),
        )
        calls_after_generation = llm.json_call_count

        listed = client.get(
            f"/api/v1/courses/{course_id}/flashcards", headers=auth(token)
        )

        assert listed.status_code == 200
        assert listed.json()
        assert llm.json_call_count == calls_after_generation

    def test_regeneration_replaces_rather_than_accumulates(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        topics = seed_course(client, token, course_id, session)
        llm.json_response = flashcard_payload(2)
        body = {"topic_ids": [str(topics["DNS Resolution"].id)]}

        client.post(
            f"/api/v1/courses/{course_id}/flashcards", json=body, headers=auth(token)
        )
        client.post(
            f"/api/v1/courses/{course_id}/flashcards", json=body, headers=auth(token)
        )

        session.expire_all()
        stored = session.scalars(select(Flashcard)).all()
        assert len(stored) == 2

    def test_a_fabricated_source_reference_is_rejected(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        topics = seed_course(client, token, course_id, session)
        llm.json_response = {
            "cards": [{"front": "F", "back": "B", "excerpt_number": 999}]
        }

        response = client.post(
            f"/api/v1/courses/{course_id}/flashcards",
            json={"topic_ids": [str(topics["DNS Resolution"].id)]},
            headers=auth(token),
        )

        assert response.status_code == 400

    def test_weak_topics_mode_uses_deterministic_selection(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        topics = seed_course(client, token, course_id, session)
        import uuid as _uuid

        me = client.get("/api/v1/auth/me", headers=auth(token)).json()
        user_id = _uuid.UUID(me["id"])
        set_mastery(
            session, user_id, course_id, topics["TCP Congestion Control"], 95.0, 25
        )
        set_mastery(session, user_id, course_id, topics["DNS Resolution"], 12.0, 9)
        llm.json_response = flashcard_payload(2)

        response = client.post(
            f"/api/v1/courses/{course_id}/flashcards",
            json={"weak_topics_only": True},
            headers=auth(token),
        )

        assert response.status_code == 201
        # DNS is the weaker topic, so it must be covered.
        assert any(card["topic_name"] == "DNS Resolution" for card in response.json())

    def test_generation_without_topics_is_refused(
        self, client: TestClient, token: str, course_id: str, llm
    ) -> None:
        response = client.post(
            f"/api/v1/courses/{course_id}/flashcards", json={}, headers=auth(token)
        )

        assert response.status_code == 400
        assert llm.json_call_count == 0


class TestIsolation:
    def test_cannot_generate_flashcards_in_another_users_course(
        self, client: TestClient, other_token: str, course_id: str, llm
    ) -> None:
        response = client.post(
            f"/api/v1/courses/{course_id}/flashcards", json={}, headers=auth(other_token)
        )

        assert response.status_code == 404
        assert llm.json_call_count == 0

    def test_cannot_list_another_users_flashcards(
        self,
        client: TestClient,
        token: str,
        other_token: str,
        course_id: str,
        session: Session,
        llm,
    ) -> None:
        topics = seed_course(client, token, course_id, session)
        llm.json_response = flashcard_payload(2)
        client.post(
            f"/api/v1/courses/{course_id}/flashcards",
            json={"topic_ids": [str(topics["DNS Resolution"].id)]},
            headers=auth(token),
        )

        response = client.get(
            f"/api/v1/courses/{course_id}/flashcards", headers=auth(other_token)
        )

        assert response.status_code == 404

    def test_flashcards_require_authentication(
        self, client: TestClient, course_id: str
    ) -> None:
        assert client.get(f"/api/v1/courses/{course_id}/flashcards").status_code == 401
        assert (
            client.post(f"/api/v1/courses/{course_id}/flashcards", json={}).status_code
            == 401
        )
