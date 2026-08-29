"""Taking a quiz end to end: attempts, answers, scoring and mastery updates."""

import io

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import QuizQuestion, TopicMastery
from app.tests.conftest import auth, make_topic, quiz_payload

NOTES = (
    b"TCP provides reliable delivery using sequence numbers and acknowledgements. "
    b"On detecting packet loss the congestion window is halved, draining the "
    b"bottleneck queue. Additive increase then probes for capacity again."
)
TOPIC_DESCRIPTION = (
    "Reliable delivery using sequence numbers and acknowledgements, and halving "
    "the congestion window on packet loss."
)


def build_quiz(client, token, course_id, session, llm, count=3):
    """Generate a quiz. `count` is at least 3 — the API's minimum quiz length."""
    from sqlalchemy import select as _select

    from app.models import Topic

    existing = session.scalar(
        _select(Topic).where(
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
        make_topic(session, course_id, "TCP Congestion Control", TOPIC_DESCRIPTION)
        session.flush()

    llm.json_response = quiz_payload(count)

    response = client.post(
        f"/api/v1/courses/{course_id}/quizzes",
        json={"mode": "standard", "question_count": count},
        headers=auth(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def answer_key(session: Session, quiz_id: str) -> dict[str, int]:
    return {
        str(question.id): question.correct_index
        for question in session.scalars(
            select(QuizQuestion).where(QuizQuestion.quiz_id == quiz_id)
        )
    }


class TestAttemptLifecycle:
    def test_start_answer_and_complete(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        quiz = build_quiz(client, token, course_id, session, llm, count=3)
        key = answer_key(session, quiz["id"])

        attempt = client.post(
            f"/api/v1/quizzes/{quiz['id']}/attempts", headers=auth(token)
        ).json()
        assert attempt["completed_at"] is None

        for question in quiz["questions"]:
            result = client.post(
                f"/api/v1/attempts/{attempt['id']}/answers",
                json={
                    "question_id": question["id"],
                    "selected_index": key[question["id"]],
                },
                headers=auth(token),
            )
            assert result.status_code == 200
            assert result.json()["is_correct"] is True

        summary = client.post(
            f"/api/v1/attempts/{attempt['id']}/complete", headers=auth(token)
        ).json()

        assert summary["score_percent"] == 100.0
        assert summary["correct_count"] == 3
        assert summary["completed_at"] is not None

    def test_answering_reveals_the_result_and_source(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        """The explanation and citation appear only after committing an answer."""
        quiz = build_quiz(client, token, course_id, session, llm)
        attempt = client.post(
            f"/api/v1/quizzes/{quiz['id']}/attempts", headers=auth(token)
        ).json()

        result = client.post(
            f"/api/v1/attempts/{attempt['id']}/answers",
            json={"question_id": quiz["questions"][0]["id"], "selected_index": 0},
            headers=auth(token),
        ).json()

        assert "correct_index" in result
        assert result["explanation"]
        assert result["source"]["document_name"] == "notes.txt"
        # TXT has no real pages, so no page number is fabricated.
        assert result["source"]["page_number"] is None

    def test_unanswered_questions_count_against_the_score(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        """Skipping is not the same as getting it right."""
        quiz = build_quiz(client, token, course_id, session, llm, count=4)
        key = answer_key(session, quiz["id"])
        attempt = client.post(
            f"/api/v1/quizzes/{quiz['id']}/attempts", headers=auth(token)
        ).json()

        first = quiz["questions"][0]
        client.post(
            f"/api/v1/attempts/{attempt['id']}/answers",
            json={"question_id": first["id"], "selected_index": key[first["id"]]},
            headers=auth(token),
        )

        summary = client.post(
            f"/api/v1/attempts/{attempt['id']}/complete", headers=auth(token)
        ).json()

        assert summary["score_percent"] == 25.0

    def test_answers_cannot_be_submitted_after_completion(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        quiz = build_quiz(client, token, course_id, session, llm, count=3)
        attempt = client.post(
            f"/api/v1/quizzes/{quiz['id']}/attempts", headers=auth(token)
        ).json()
        client.post(f"/api/v1/attempts/{attempt['id']}/complete", headers=auth(token))

        response = client.post(
            f"/api/v1/attempts/{attempt['id']}/answers",
            json={"question_id": quiz["questions"][0]["id"], "selected_index": 0},
            headers=auth(token),
        )

        assert response.status_code == 400

    def test_a_question_from_another_quiz_cannot_be_answered(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        first = build_quiz(client, token, course_id, session, llm, count=3)
        second = build_quiz(client, token, course_id, session, llm, count=3)
        attempt = client.post(
            f"/api/v1/quizzes/{first['id']}/attempts", headers=auth(token)
        ).json()

        response = client.post(
            f"/api/v1/attempts/{attempt['id']}/answers",
            json={"question_id": second["questions"][0]["id"], "selected_index": 0},
            headers=auth(token),
        )

        assert response.status_code == 404


class TestMasteryIntegration:
    def test_answering_creates_and_updates_mastery(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        quiz = build_quiz(client, token, course_id, session, llm, count=3)
        key = answer_key(session, quiz["id"])
        attempt = client.post(
            f"/api/v1/quizzes/{quiz['id']}/attempts", headers=auth(token)
        ).json()

        for question in quiz["questions"]:
            client.post(
                f"/api/v1/attempts/{attempt['id']}/answers",
                json={
                    "question_id": question["id"],
                    "selected_index": key[question["id"]],
                },
                headers=auth(token),
            )

        session.expire_all()
        row = session.scalar(select(TopicMastery))
        assert row is not None
        assert row.questions_attempted == 3
        assert row.correct_answers == 3
        assert row.mastery_score > 0

    def test_wrong_answers_lower_mastery(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        quiz = build_quiz(client, token, course_id, session, llm, count=3)
        key = answer_key(session, quiz["id"])
        attempt = client.post(
            f"/api/v1/quizzes/{quiz['id']}/attempts", headers=auth(token)
        ).json()

        for question in quiz["questions"]:
            wrong = (key[question["id"]] + 1) % 4
            client.post(
                f"/api/v1/attempts/{attempt['id']}/answers",
                json={"question_id": question["id"], "selected_index": wrong},
                headers=auth(token),
            )

        session.expire_all()
        row = session.scalar(select(TopicMastery))
        assert row.correct_answers == 0
        assert row.mastery_score == 0.0
        assert row.last_answer_correct is False

    def test_changing_an_answer_does_not_double_count_mastery(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        """Otherwise a student could farm a topic by toggling options."""
        quiz = build_quiz(client, token, course_id, session, llm, count=3)
        question = quiz["questions"][0]
        attempt = client.post(
            f"/api/v1/quizzes/{quiz['id']}/attempts", headers=auth(token)
        ).json()

        for index in (0, 1, 2, 3):
            client.post(
                f"/api/v1/attempts/{attempt['id']}/answers",
                json={"question_id": question["id"], "selected_index": index},
                headers=auth(token),
            )

        session.expire_all()
        row = session.scalar(select(TopicMastery))
        assert row.questions_attempted == 1

    def test_mastery_endpoint_reflects_the_attempt(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        quiz = build_quiz(client, token, course_id, session, llm, count=3)
        key = answer_key(session, quiz["id"])
        attempt = client.post(
            f"/api/v1/quizzes/{quiz['id']}/attempts", headers=auth(token)
        ).json()
        for question in quiz["questions"]:
            client.post(
                f"/api/v1/attempts/{attempt['id']}/answers",
                json={
                    "question_id": question["id"],
                    "selected_index": key[question["id"]],
                },
                headers=auth(token),
            )

        mastery = client.get(
            f"/api/v1/courses/{course_id}/mastery", headers=auth(token)
        ).json()

        assert mastery["questions_answered"] == 3
        assert mastery["correct_answers"] == 3
        assert mastery["topics_started"] == 1
        # Practised mastery covers what has been studied; course mastery counts
        # every active topic, so with one topic started they agree here.
        assert mastery["practised_mastery"] is not None
        assert mastery["course_mastery"] > 0
        assert mastery["coverage"] == 1.0


class TestEmptyState:
    def test_mastery_for_a_new_student_is_honest(
        self, client: TestClient, token: str, course_id: str, session: Session
    ) -> None:
        """Nothing attempted is not the same as zero mastery."""
        make_topic(session, course_id, "Untouched Topic")
        session.flush()

        mastery = client.get(
            f"/api/v1/courses/{course_id}/mastery", headers=auth(token)
        ).json()

        # Nothing practised: no practised average exists, and course mastery is a
        # real 0 rather than a missing value — the student has covered nothing.
        assert mastery["practised_mastery"] is None
        assert mastery["course_mastery"] == 0.0
        assert mastery["coverage"] == 0.0
        assert mastery["accuracy"] is None
        assert mastery["strongest_topic"] is None
        assert mastery["topics_started"] == 0

        topic = mastery["topics"][0]
        assert topic["band"] == "not_started"
        assert topic["effective_band"] == "not_started"
        assert topic["retention_status"] == "new"
        assert topic["accuracy"] is None
        assert topic["days_since_practice"] is None


class TestIsolation:
    def test_cannot_start_an_attempt_on_another_users_quiz(
        self,
        client: TestClient,
        token: str,
        other_token: str,
        course_id: str,
        session: Session,
        llm,
    ) -> None:
        quiz = build_quiz(client, token, course_id, session, llm, count=3)

        response = client.post(
            f"/api/v1/quizzes/{quiz['id']}/attempts", headers=auth(other_token)
        )

        assert response.status_code == 404

    def test_cannot_answer_in_another_users_attempt(
        self,
        client: TestClient,
        token: str,
        other_token: str,
        course_id: str,
        session: Session,
        llm,
    ) -> None:
        quiz = build_quiz(client, token, course_id, session, llm, count=3)
        attempt = client.post(
            f"/api/v1/quizzes/{quiz['id']}/attempts", headers=auth(token)
        ).json()

        response = client.post(
            f"/api/v1/attempts/{attempt['id']}/answers",
            json={"question_id": quiz["questions"][0]["id"], "selected_index": 0},
            headers=auth(other_token),
        )

        assert response.status_code == 404

    def test_cannot_complete_another_users_attempt(
        self,
        client: TestClient,
        token: str,
        other_token: str,
        course_id: str,
        session: Session,
        llm,
    ) -> None:
        quiz = build_quiz(client, token, course_id, session, llm, count=3)
        attempt = client.post(
            f"/api/v1/quizzes/{quiz['id']}/attempts", headers=auth(token)
        ).json()

        response = client.post(
            f"/api/v1/attempts/{attempt['id']}/complete", headers=auth(other_token)
        )

        assert response.status_code == 404

    def test_cannot_read_another_users_mastery(
        self, client: TestClient, other_token: str, course_id: str
    ) -> None:
        assert (
            client.get(
                f"/api/v1/courses/{course_id}/mastery", headers=auth(other_token)
            ).status_code
            == 404
        )

    def test_mastery_requires_authentication(
        self, client: TestClient, course_id: str
    ) -> None:
        assert client.get(f"/api/v1/courses/{course_id}/mastery").status_code == 401
        assert (
            client.get(f"/api/v1/courses/{course_id}/recommendations").status_code == 401
        )
