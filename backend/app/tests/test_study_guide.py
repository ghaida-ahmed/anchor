"""Study guide generation, provenance, staleness and the mastery overlay."""

import io

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import StudyGuide, StudyGuideSection, StudyGuideStatus, Topic
from app.tests.conftest import (
    OVERVIEW_PAYLOAD,
    auth,
    grade_payload,
    make_topic,
    section_payload,
)

NOTES = (
    b"On detecting packet loss the congestion window is halved, draining the "
    b"bottleneck queue. Additive increase then probes for capacity again, so the "
    b"congestion window grows by one segment per round trip."
)

TOPIC = "TCP Congestion Control"
DESCRIPTION = (
    "Halving the congestion window on packet loss, then probing additively for capacity."
)


def ground(client: TestClient, token: str, course_id: str, session: Session):
    response = client.post(
        f"/api/v1/courses/{course_id}/documents",
        files={"file": ("notes.txt", io.BytesIO(NOTES), "text/plain")},
        headers=auth(token),
    )
    assert response.status_code == 201
    topic = make_topic(session, course_id, TOPIC, DESCRIPTION)
    session.flush()
    return topic


def build(client, token, course_id, llm, *, topics: int = 1):
    """Script n section calls plus the single synthesis call."""
    llm.json_responses = [section_payload() for _ in range(topics)] + [OVERVIEW_PAYLOAD]
    return client.post(f"/api/v1/courses/{course_id}/study-guide", headers=auth(token))


class TestGeneration:
    def test_a_guide_is_generated_and_persisted(
        self, client, token, course_id, session, llm
    ) -> None:
        ground(client, token, course_id, session)
        response = build(client, token, course_id, llm)
        assert response.status_code == 201, response.text

        body = response.json()
        assert body["status"] == "ready"
        assert body["overview"]
        assert len(body["sections"]) == 1
        assert body["sections"][0]["topic_name"] == TOPIC
        assert body["sections"][0]["key_concepts"]

        assert session.scalar(select(StudyGuide)) is not None

    def test_generation_costs_one_call_per_topic_plus_one(
        self, client, token, course_id, session, llm
    ) -> None:
        ground(client, token, course_id, session)
        make_topic(
            session,
            course_id,
            "Slow Start",
            "Doubling the congestion window every round trip until loss.",
        )
        session.flush()

        before = llm.json_call_count
        build(client, token, course_id, llm, topics=2)
        assert llm.json_call_count - before == 3

    def test_sections_carry_resolvable_citations(
        self, client, token, course_id, session, llm
    ) -> None:
        ground(client, token, course_id, session)
        body = build(client, token, course_id, llm).json()

        sources = body["sections"][0]["sources"]
        assert sources
        assert sources[0]["document_name"] == "notes.txt"
        # TXT has no real pages, so no page number is invented.
        assert sources[0]["page_number"] is None

    def test_key_terms_resolve_to_real_chunks(
        self, client, token, course_id, session, llm
    ) -> None:
        ground(client, token, course_id, session)
        body = build(client, token, course_id, llm).json()

        assert body["key_terms"]
        term = body["key_terms"][0]
        assert term["term"] == "Congestion window"
        assert term["source"] is not None
        assert term["source"]["chunk_id"]

    def test_a_section_citing_nothing_real_is_dropped(
        self, client, token, course_id, session, llm
    ) -> None:
        ground(client, token, course_id, session)
        llm.json_responses = [section_payload(excerpt=99), OVERVIEW_PAYLOAD]
        response = client.post(
            f"/api/v1/courses/{course_id}/study-guide", headers=auth(token)
        )
        # The only section had no resolvable provenance, so there is no guide.
        assert response.status_code == 400

    def test_a_course_without_topics_cannot_have_a_guide(
        self, client, token, course_id, llm
    ) -> None:
        assert build(client, token, course_id, llm).status_code == 400

    def test_a_failed_generation_is_recorded(
        self, client, token, course_id, session, llm
    ) -> None:
        ground(client, token, course_id, session)
        llm.json_responses = [section_payload(excerpt=99), OVERVIEW_PAYLOAD]
        client.post(f"/api/v1/courses/{course_id}/study-guide", headers=auth(token))

        session.expire_all()
        guide = session.scalar(select(StudyGuide))
        assert guide is not None
        assert guide.status is StudyGuideStatus.FAILED
        assert guide.error_message


class TestReading:
    def test_reading_never_generates(
        self, client, token, course_id, session, llm
    ) -> None:
        ground(client, token, course_id, session)
        build(client, token, course_id, llm)

        before = llm.json_call_count
        response = client.get(
            f"/api/v1/courses/{course_id}/study-guide", headers=auth(token)
        )
        assert response.status_code == 200
        assert llm.json_call_count == before

    def test_an_ungenerated_guide_is_a_404_not_an_empty_one(
        self, client, token, course_id, session
    ) -> None:
        ground(client, token, course_id, session)
        response = client.get(
            f"/api/v1/courses/{course_id}/study-guide", headers=auth(token)
        )
        assert response.status_code == 404

    def test_regenerating_replaces_the_sections(
        self, client, token, course_id, session, llm
    ) -> None:
        ground(client, token, course_id, session)
        build(client, token, course_id, llm)
        build(client, token, course_id, llm)

        session.expire_all()
        assert len(list(session.scalars(select(StudyGuideSection)))) == 1


class TestStaleness:
    def test_uploading_new_material_marks_the_guide_stale(
        self, client, token, course_id, session, llm
    ) -> None:
        ground(client, token, course_id, session)
        build(client, token, course_id, llm)

        client.post(
            f"/api/v1/courses/{course_id}/documents",
            files={
                "file": ("more.txt", io.BytesIO(NOTES + b" More text."), "text/plain")
            },
            headers=auth(token),
        )

        body = client.get(
            f"/api/v1/courses/{course_id}/study-guide", headers=auth(token)
        ).json()
        assert body["status"] == "stale"
        assert body["is_stale"] is True
        # Still readable — stale means "no longer known to match", not "gone".
        assert body["sections"]

    def test_a_new_topic_marks_the_guide_stale(
        self, client, token, course_id, session, llm
    ) -> None:
        ground(client, token, course_id, session)
        build(client, token, course_id, llm)

        make_topic(session, course_id, "Slow Start", "Doubling the window.")
        session.commit()

        body = client.get(
            f"/api/v1/courses/{course_id}/study-guide", headers=auth(token)
        ).json()
        assert body["is_stale"] is True

    def test_answering_a_question_does_not_make_the_guide_stale(
        self, client, token, course_id, session, llm
    ) -> None:
        """Mastery is overlaid at read time, so studying must not invalidate text."""
        ground(client, token, course_id, session)
        build(client, token, course_id, llm)

        from app.tests.conftest import short_answer_payload

        llm.json_response = short_answer_payload(1)
        quiz = client.post(
            f"/api/v1/courses/{course_id}/quizzes",
            json={
                "mode": "standard",
                "question_count": 3,
                "quiz_format": "short_answer",
            },
            headers=auth(token),
        ).json()
        attempt = client.post(
            f"/api/v1/quizzes/{quiz['id']}/attempts", headers=auth(token)
        ).json()
        llm.json_response = grade_payload("correct")
        client.post(
            f"/api/v1/attempts/{attempt['id']}/short-answers",
            json={
                "question_id": quiz["questions"][0]["id"],
                "response_text": "It halves on loss, then probes additively.",
            },
            headers=auth(token),
        )

        body = client.get(
            f"/api/v1/courses/{course_id}/study-guide", headers=auth(token)
        ).json()
        assert body["status"] == "ready"
        assert body["is_stale"] is False
        # ...but the overlay has moved.
        assert body["sections"][0]["mastery"] > 0

    def test_regeneration_clears_staleness(
        self, client, token, course_id, session, llm
    ) -> None:
        ground(client, token, course_id, session)
        build(client, token, course_id, llm)
        make_topic(session, course_id, "Slow Start", "Doubling the window.")
        session.commit()

        assert client.get(
            f"/api/v1/courses/{course_id}/study-guide", headers=auth(token)
        ).json()["is_stale"]

        rebuilt = build(client, token, course_id, llm, topics=2).json()
        assert rebuilt["status"] == "ready"
        assert rebuilt["is_stale"] is False


class TestOverlay:
    def test_an_unstudied_topic_reads_as_not_started(
        self, client, token, course_id, session, llm
    ) -> None:
        ground(client, token, course_id, session)
        body = build(client, token, course_id, llm).json()
        section = body["sections"][0]
        assert section["band"] == "not_started"
        assert section["band_label"] == "Not started"
        assert section["mastery"] == 0.0

    def test_a_deactivated_topics_section_is_not_shown(
        self, client, token, course_id, session, llm
    ) -> None:
        ground(client, token, course_id, session)
        build(client, token, course_id, llm)

        topic = session.scalar(select(Topic).where(Topic.course_id == course_id))
        topic.is_active = False
        session.commit()

        body = client.get(
            f"/api/v1/courses/{course_id}/study-guide", headers=auth(token)
        ).json()
        assert body["sections"] == []


class TestIsolation:
    def test_another_user_cannot_read_this_guide(
        self, client, token, other_token, course_id, session, llm
    ) -> None:
        ground(client, token, course_id, session)
        build(client, token, course_id, llm)
        response = client.get(
            f"/api/v1/courses/{course_id}/study-guide", headers=auth(other_token)
        )
        assert response.status_code == 404

    def test_another_user_cannot_generate_this_guide(
        self, client, token, other_token, course_id, session, llm
    ) -> None:
        ground(client, token, course_id, session)
        assert build(client, other_token, course_id, llm).status_code == 404
