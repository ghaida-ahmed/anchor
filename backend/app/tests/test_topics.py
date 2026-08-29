"""Topic extraction: grounding, validation, regeneration and isolation."""

import io

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Topic
from app.tests.conftest import auth

NOTES = (
    b"TCP provides reliable delivery using sequence numbers and acknowledgements. "
    b"On packet loss the congestion window is halved. The Domain Name System "
    b"resolves names into IP addresses."
)


def upload(client: TestClient, token: str, course_id: str, name: str, data: bytes) -> str:
    response = client.post(
        f"/api/v1/courses/{course_id}/documents",
        files={"file": (name, io.BytesIO(data), "text/plain")},
        headers=auth(token),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def extract(client: TestClient, token: str, course_id: str):
    return client.post(f"/api/v1/courses/{course_id}/topics/extract", headers=auth(token))


def topics_payload(*names: str) -> dict:
    return {
        "topics": [
            {"name": name, "description": f"About {name}.", "excerpt_number": 1}
            for name in names
        ]
    }


class TestExtraction:
    def test_topics_are_derived_from_uploaded_material(
        self, client: TestClient, token: str, course_id: str, llm
    ) -> None:
        upload(client, token, course_id, "notes.txt", NOTES)
        llm.json_response = topics_payload("TCP Congestion Control", "DNS Resolution")

        response = extract(client, token, course_id)

        assert response.status_code == 200
        names = {topic["name"] for topic in response.json()["created"]}
        assert names == {"TCP Congestion Control", "DNS Resolution"}

    def test_extraction_is_given_the_course_material(
        self, client: TestClient, token: str, course_id: str, llm
    ) -> None:
        """The prompt must carry excerpts, not just the course title."""
        upload(client, token, course_id, "notes.txt", NOTES)
        llm.json_response = topics_payload("TCP Congestion Control")

        extract(client, token, course_id)

        assert "congestion window is halved" in llm.last_json_prompt
        assert "[Excerpt 1]" in llm.last_json_prompt

    def test_extraction_without_material_is_refused(
        self, client: TestClient, token: str, course_id: str, llm
    ) -> None:
        """No grounding, no topics — never invent them from the course title."""
        response = extract(client, token, course_id)

        assert response.status_code == 400
        assert "no processed course material" in response.json()["detail"].lower()
        assert llm.json_call_count == 0

    def test_only_ready_documents_are_used(
        self, client: TestClient, token: str, course_id: str, llm
    ) -> None:
        from app.tests.factories import make_image_only_pdf

        upload(client, token, course_id, "scan.pdf", make_image_only_pdf())

        response = extract(client, token, course_id)

        assert response.status_code == 400


class TestValidation:
    def test_duplicate_names_collapse(
        self, client: TestClient, token: str, course_id: str, llm
    ) -> None:
        upload(client, token, course_id, "notes.txt", NOTES)
        llm.json_response = topics_payload(
            "TCP Congestion Control", "tcp congestion control", "TCP  Congestion  Control"
        )

        response = extract(client, token, course_id)

        assert len(response.json()["created"]) == 1

    def test_meaningless_topics_are_rejected(
        self, client: TestClient, token: str, course_id: str, llm
    ) -> None:
        upload(client, token, course_id, "notes.txt", NOTES)
        llm.json_response = topics_payload("Introduction", "Summary", "DNS Resolution")

        names = {t["name"] for t in extract(client, token, course_id).json()["created"]}

        assert names == {"DNS Resolution"}

    def test_a_topic_restating_the_course_title_is_rejected(
        self, client: TestClient, token: str, course_id: str, llm
    ) -> None:
        """The fixture course is "Computer Networks"."""
        upload(client, token, course_id, "notes.txt", NOTES)
        llm.json_response = topics_payload("Computer Networks", "DNS Resolution")

        names = {t["name"] for t in extract(client, token, course_id).json()["created"]}

        assert names == {"DNS Resolution"}

    def test_malformed_output_yields_an_honest_error(
        self, client: TestClient, token: str, course_id: str, llm
    ) -> None:
        upload(client, token, course_id, "notes.txt", NOTES)
        llm.json_response = {"unexpected": "shape"}

        response = extract(client, token, course_id)

        assert response.status_code == 400
        assert "no clear topics" in response.json()["detail"].lower()


class TestRegeneration:
    def test_rerunning_does_not_duplicate_topics(
        self, client: TestClient, token: str, course_id: str, llm, session: Session
    ) -> None:
        upload(client, token, course_id, "notes.txt", NOTES)
        llm.json_response = topics_payload("TCP Congestion Control", "DNS Resolution")

        extract(client, token, course_id)
        second = extract(client, token, course_id)

        assert second.json()["created"] == []
        assert len(second.json()["unchanged"]) == 2
        stored = session.scalars(select(Topic).where(Topic.course_id == course_id)).all()
        assert len(stored) == 2

    def test_a_vanished_topic_is_deactivated_not_deleted(
        self, client: TestClient, token: str, course_id: str, llm, session: Session
    ) -> None:
        """Mastery references topics; deleting one would destroy the student's history."""
        upload(client, token, course_id, "notes.txt", NOTES)
        llm.json_response = topics_payload("TCP Congestion Control", "DNS Resolution")
        extract(client, token, course_id)

        llm.json_response = topics_payload("TCP Congestion Control")
        second = extract(client, token, course_id)

        assert [t["name"] for t in second.json()["deactivated"]] == ["DNS Resolution"]
        still_there = session.scalars(
            select(Topic).where(Topic.course_id == course_id)
        ).all()
        assert len(still_there) == 2

    def test_deactivated_topics_are_hidden_by_default(
        self, client: TestClient, token: str, course_id: str, llm
    ) -> None:
        upload(client, token, course_id, "notes.txt", NOTES)
        llm.json_response = topics_payload("TCP Congestion Control", "DNS Resolution")
        extract(client, token, course_id)
        llm.json_response = topics_payload("TCP Congestion Control")
        extract(client, token, course_id)

        active = client.get(f"/api/v1/courses/{course_id}/topics", headers=auth(token))
        everything = client.get(
            f"/api/v1/courses/{course_id}/topics?include_inactive=true",
            headers=auth(token),
        )

        assert len(active.json()) == 1
        assert len(everything.json()) == 2

    def test_a_returning_topic_is_reactivated_not_duplicated(
        self, client: TestClient, token: str, course_id: str, llm
    ) -> None:
        upload(client, token, course_id, "notes.txt", NOTES)
        llm.json_response = topics_payload("TCP Congestion Control", "DNS Resolution")
        extract(client, token, course_id)
        llm.json_response = topics_payload("TCP Congestion Control")
        extract(client, token, course_id)

        llm.json_response = topics_payload("TCP Congestion Control", "DNS Resolution")
        third = extract(client, token, course_id)

        assert [t["name"] for t in third.json()["reactivated"]] == ["DNS Resolution"]
        assert third.json()["created"] == []


class TestIsolation:
    def test_cannot_list_another_users_topics(
        self, client: TestClient, token: str, other_token: str, course_id: str, llm
    ) -> None:
        upload(client, token, course_id, "notes.txt", NOTES)
        llm.json_response = topics_payload("TCP Congestion Control")
        extract(client, token, course_id)

        response = client.get(
            f"/api/v1/courses/{course_id}/topics", headers=auth(other_token)
        )

        assert response.status_code == 404

    def test_cannot_extract_topics_in_another_users_course(
        self, client: TestClient, other_token: str, course_id: str, llm
    ) -> None:
        response = extract(client, other_token, course_id)

        assert response.status_code == 404
        assert llm.json_call_count == 0

    def test_topics_require_authentication(
        self, client: TestClient, course_id: str
    ) -> None:
        assert client.get(f"/api/v1/courses/{course_id}/topics").status_code == 401
        assert (
            client.post(f"/api/v1/courses/{course_id}/topics/extract").status_code == 401
        )
