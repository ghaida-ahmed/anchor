"""Quiz generation, validation, grounding and the answer-hiding guarantee."""

import io

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Difficulty, QuizQuestion
from app.tests.conftest import auth, make_topic, quiz_payload

NOTES = (
    b"TCP provides reliable delivery using sequence numbers and acknowledgements. "
    b"On detecting packet loss the congestion window is halved, draining the "
    b"bottleneck queue. Additive increase then probes for capacity again."
)


# The description is phrased from the material, which is what real extraction
# produces ("one sentence, drawn from the excerpts") and what the lexical test
# provider needs in order to retrieve anything at all.
TOPIC_DESCRIPTION = (
    "Reliable delivery using sequence numbers and acknowledgements, and halving "
    "the congestion window on packet loss."
)


def ground(
    client: TestClient,
    token: str,
    course_id: str,
    session: Session,
    topic: str = "TCP Congestion Control",
):
    """Upload material and create a topic, ready for generation."""
    response = client.post(
        f"/api/v1/courses/{course_id}/documents",
        files={"file": ("notes.txt", io.BytesIO(NOTES), "text/plain")},
        headers=auth(token),
    )
    assert response.status_code == 201
    created = make_topic(session, course_id, topic, TOPIC_DESCRIPTION)
    session.flush()
    return created


def generate(client: TestClient, token: str, course_id: str, **body):
    payload = {"mode": "standard", "question_count": 3, **body}
    return client.post(
        f"/api/v1/courses/{course_id}/quizzes", json=payload, headers=auth(token)
    )


class TestGrounding:
    def test_generated_quiz_is_persisted(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        ground(client, token, course_id, session)
        llm.json_response = quiz_payload(3)

        response = generate(client, token, course_id)

        assert response.status_code == 201
        body = response.json()
        assert len(body["questions"]) == 3
        assert body["mode"] == "standard"

    def test_the_model_is_given_course_excerpts(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        ground(client, token, course_id, session)
        llm.json_response = quiz_payload(2)

        generate(client, token, course_id)

        assert "congestion window is halved" in llm.last_json_prompt
        assert "[Excerpt 1]" in llm.last_json_prompt

    def test_generation_without_material_is_refused(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        """A topic with no supporting chunks must not become a quiz."""
        make_topic(session, course_id, "Unsupported Topic")
        session.flush()
        llm.json_response = quiz_payload(3)

        response = generate(client, token, course_id)

        assert response.status_code == 400
        assert "not enough information" in response.json()["detail"].lower()

    def test_generation_without_topics_is_refused(
        self, client: TestClient, token: str, course_id: str, llm
    ) -> None:
        response = generate(client, token, course_id)

        assert response.status_code == 400
        assert "no topics" in response.json()["detail"].lower()
        assert llm.json_call_count == 0


class TestValidation:
    def test_a_question_with_three_options_is_rejected(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        ground(client, token, course_id, session)
        bad = quiz_payload(1)
        bad["questions"][0]["options"] = ["A", "B", "C"]
        llm.json_responses = [bad, bad]

        response = generate(client, token, course_id)

        assert response.status_code == 400

    def test_duplicate_options_are_rejected(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        """Duplicates make "exactly one correct answer" meaningless."""
        ground(client, token, course_id, session)
        bad = quiz_payload(1)
        bad["questions"][0]["options"] = ["Same", "Same", "Other", "Another"]
        llm.json_responses = [bad, bad]

        assert generate(client, token, course_id).status_code == 400

    def test_an_out_of_range_correct_index_is_rejected(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        ground(client, token, course_id, session)
        bad = quiz_payload(1)
        bad["questions"][0]["correct_index"] = 9
        llm.json_responses = [bad, bad]

        assert generate(client, token, course_id).status_code == 400

    def test_an_empty_explanation_is_rejected(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        ground(client, token, course_id, session)
        bad = quiz_payload(1)
        bad["questions"][0]["explanation"] = "   "
        llm.json_responses = [bad, bad]

        assert generate(client, token, course_id).status_code == 400

    def test_an_invalid_difficulty_is_rejected(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        ground(client, token, course_id, session)
        bad = quiz_payload(1)
        bad["questions"][0]["difficulty"] = "impossible"
        llm.json_responses = [bad, bad]

        assert generate(client, token, course_id).status_code == 400

    def test_a_fabricated_source_reference_is_rejected(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        """Citing an excerpt we never supplied would mean invented provenance."""
        ground(client, token, course_id, session)
        bad = quiz_payload(1, excerpt=999)
        llm.json_responses = [bad, bad]

        assert generate(client, token, course_id).status_code == 400

    def test_malformed_output_is_retried_once_then_fails(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        ground(client, token, course_id, session)
        llm.json_responses = [{"garbage": True}, quiz_payload(2)]

        response = generate(client, token, course_id)

        assert response.status_code == 201
        assert llm.json_call_count == 2

    def test_nothing_is_saved_when_generation_fails(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        ground(client, token, course_id, session)
        llm.json_responses = [{"questions": []}, {"questions": []}]

        generate(client, token, course_id)

        assert (
            client.get(f"/api/v1/courses/{course_id}/quizzes", headers=auth(token)).json()
            == []
        )


class TestAnswerHiding:
    def test_the_taking_view_hides_the_correct_answer(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        """The single most important contract in this feature."""
        ground(client, token, course_id, session)
        llm.json_response = quiz_payload(3)

        body = generate(client, token, course_id).json()

        for question in body["questions"]:
            assert "correct_index" not in question
            assert "explanation" not in question
            assert "source" not in question
            assert len(question["options"]) == 4

    def test_reading_a_quiz_back_also_hides_the_answer(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        ground(client, token, course_id, session)
        llm.json_response = quiz_payload(2)
        quiz_id = generate(client, token, course_id).json()["id"]

        body = client.get(f"/api/v1/quizzes/{quiz_id}", headers=auth(token)).json()

        assert all("correct_index" not in q for q in body["questions"])

    def test_the_raw_response_never_contains_the_answer_key(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        ground(client, token, course_id, session)
        llm.json_response = quiz_payload(3)
        quiz_id = generate(client, token, course_id).json()["id"]

        raw = client.get(f"/api/v1/quizzes/{quiz_id}", headers=auth(token)).text

        assert "correct_index" not in raw
        assert "Because the excerpt says so" not in raw


class TestProvenance:
    def test_questions_record_their_source_chunk(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        ground(client, token, course_id, session)
        llm.json_response = quiz_payload(2)
        quiz_id = generate(client, token, course_id).json()["id"]

        stored = session.scalars(
            select(QuizQuestion).where(QuizQuestion.quiz_id == quiz_id)
        ).all()

        assert stored
        for question in stored:
            assert question.source_chunk_id is not None
            assert question.source_document_id is not None

    def test_difficulty_is_persisted(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        ground(client, token, course_id, session)
        llm.json_response = quiz_payload(2, difficulty="hard")
        quiz_id = generate(client, token, course_id).json()["id"]

        stored = session.scalars(
            select(QuizQuestion).where(QuizQuestion.quiz_id == quiz_id)
        ).all()

        assert all(q.difficulty is Difficulty.HARD for q in stored)


class TestIsolation:
    def test_cannot_generate_in_another_users_course(
        self, client: TestClient, other_token: str, course_id: str, llm
    ) -> None:
        response = generate(client, other_token, course_id)

        assert response.status_code == 404
        assert llm.json_call_count == 0

    def test_cannot_read_another_users_quiz(
        self,
        client: TestClient,
        token: str,
        other_token: str,
        course_id: str,
        session: Session,
        llm,
    ) -> None:
        ground(client, token, course_id, session)
        llm.json_response = quiz_payload(2)
        quiz_id = generate(client, token, course_id).json()["id"]

        assert (
            client.get(
                f"/api/v1/quizzes/{quiz_id}", headers=auth(other_token)
            ).status_code
            == 404
        )

    def test_cannot_list_another_users_quizzes(
        self, client: TestClient, other_token: str, course_id: str
    ) -> None:
        assert (
            client.get(
                f"/api/v1/courses/{course_id}/quizzes", headers=auth(other_token)
            ).status_code
            == 404
        )

    def test_quiz_endpoints_require_authentication(
        self, client: TestClient, course_id: str
    ) -> None:
        assert client.get(f"/api/v1/courses/{course_id}/quizzes").status_code == 401
        assert (
            client.post(f"/api/v1/courses/{course_id}/quizzes", json={}).status_code
            == 401
        )
