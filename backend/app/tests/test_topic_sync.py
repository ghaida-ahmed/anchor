"""Topics staying in step with a course's material, automatically.

The workflow this replaces: upload a lecture, open the Study Guide, find it empty,
and have no way to know that "extract topics" was a prerequisite. Topics now update
themselves once a document reaches READY, and the manual action exists only for
when that did not happen.

The automatic step is disabled for most of the suite (see `conftest`), because it
would consume scripted model responses other tests assert on. Cases here that want
it ask for the `automatic_topic_sync` fixture explicitly.
"""

import io

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Course, Topic, TopicMastery
from app.services.learning.material import material_fingerprint
from app.services.learning.topic_service import TopicService
from app.tests.conftest import auth, make_topic

LECTURE_ONE = (
    b"Congestion arises when the aggregate demand offered to a link exceeds its "
    b"capacity. Queues build at the bottleneck router and packets are discarded "
    b"once the buffer is full. The sender maintains a congestion window."
)
LECTURE_TWO = (
    b"The Domain Name System is a distributed hierarchical database that "
    b"translates human readable names into numeric addresses. A resolver queries "
    b"a root server, then a top level domain server, then the authoritative one."
)


def topics_payload(*names: str) -> dict:
    return {
        "topics": [
            {
                "name": name,
                "description": f"What the excerpts say about {name}.",
                "excerpt_number": 1,
            }
            for name in names
        ]
    }


def upload(client: TestClient, token: str, course_id: str, body: bytes, name: str):
    return client.post(
        f"/api/v1/courses/{course_id}/documents",
        files={"file": (name, io.BytesIO(body), "text/plain")},
        headers=auth(token),
    )


def wait_ready(client: TestClient, token: str, course_id: str) -> list[dict]:
    """Processing runs inline in tests, so one read is enough."""
    return client.get(
        f"/api/v1/courses/{course_id}/documents", headers=auth(token)
    ).json()


def status(client: TestClient, token: str, course_id: str) -> dict:
    return client.get(
        f"/api/v1/courses/{course_id}/topics/status", headers=auth(token)
    ).json()


class TestSyncState:
    """The persisted answer to 'do topics reflect the material?'"""

    def test_an_empty_course_is_never_out_of_sync(
        self, client: TestClient, token: str, course_id: str
    ) -> None:
        """Nothing to extract from, so prompting would be noise."""
        body = status(client, token, course_id)
        assert body["topics_are_current"] is True
        assert body["ready_document_count"] == 0
        assert body["topic_count"] == 0

    def test_ready_material_with_no_topics_is_out_of_sync(
        self, client: TestClient, token: str, course_id: str
    ) -> None:
        upload(client, token, course_id, LECTURE_ONE, "lecture-01.txt")
        body = status(client, token, course_id)
        assert body["ready_document_count"] == 1
        assert body["topics_are_current"] is False

    def test_extracting_brings_it_into_sync(
        self, client: TestClient, token: str, course_id: str, llm
    ) -> None:
        upload(client, token, course_id, LECTURE_ONE, "lecture-01.txt")
        llm.json_response = topics_payload("Congestion Control")

        response = client.post(
            f"/api/v1/courses/{course_id}/topics/extract", headers=auth(token)
        )
        assert response.status_code == 200
        assert status(client, token, course_id)["topics_are_current"] is True

    def test_new_material_puts_it_back_out_of_sync(
        self, client: TestClient, token: str, course_id: str, llm
    ) -> None:
        upload(client, token, course_id, LECTURE_ONE, "lecture-01.txt")
        llm.json_response = topics_payload("Congestion Control")
        client.post(f"/api/v1/courses/{course_id}/topics/extract", headers=auth(token))
        assert status(client, token, course_id)["topics_are_current"] is True

        upload(client, token, course_id, LECTURE_TWO, "lecture-02.txt")
        assert status(client, token, course_id)["topics_are_current"] is False

    def test_the_fingerprint_survives_a_new_session(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        """It is a column, not memory: a restart or a cold start must not lose it."""
        upload(client, token, course_id, LECTURE_ONE, "lecture-01.txt")
        llm.json_response = topics_payload("Congestion Control")
        client.post(f"/api/v1/courses/{course_id}/topics/extract", headers=auth(token))

        session.expire_all()
        course = session.get(Course, course_id)
        assert course.topics_fingerprint
        assert course.topics_fingerprint == material_fingerprint(session, course.id)

    def test_deleting_a_document_changes_the_fingerprint(
        self, client: TestClient, token: str, course_id: str, llm
    ) -> None:
        upload(client, token, course_id, LECTURE_ONE, "lecture-01.txt")
        second = upload(client, token, course_id, LECTURE_TWO, "lecture-02.txt").json()
        llm.json_response = topics_payload("Congestion Control", "DNS")
        client.post(f"/api/v1/courses/{course_id}/topics/extract", headers=auth(token))
        assert status(client, token, course_id)["topics_are_current"] is True

        client.delete(f"/api/v1/documents/{second['id']}", headers=auth(token))
        assert status(client, token, course_id)["topics_are_current"] is False

    def test_a_failed_document_does_not_make_the_course_out_of_sync(
        self, client: TestClient, token: str, course_id: str, session: Session
    ) -> None:
        """Only READY material counts — a document that never processed has no
        chunks to extract anything from."""
        upload(client, token, course_id, b"", "empty.txt")
        documents = wait_ready(client, token, course_id)
        assert documents == [] or documents[0]["processing_status"] != "ready"
        assert status(client, token, course_id)["topics_are_current"] is True


class TestAutomaticSync:
    """The point of the change: the student never has to know about extraction."""

    def test_the_first_document_generates_topics_with_no_manual_step(
        self, client: TestClient, token: str, course_id: str, llm, automatic_topic_sync
    ) -> None:
        llm.json_response = topics_payload("Congestion Control", "Flow Control")

        upload(client, token, course_id, LECTURE_ONE, "lecture-01.txt")

        topics = client.get(
            f"/api/v1/courses/{course_id}/topics", headers=auth(token)
        ).json()
        assert {t["name"] for t in topics} == {"Congestion Control", "Flow Control"}
        assert status(client, token, course_id)["topics_are_current"] is True

    def test_a_later_document_updates_topics_automatically(
        self, client: TestClient, token: str, course_id: str, llm, automatic_topic_sync
    ) -> None:
        llm.json_response = topics_payload("Congestion Control")
        upload(client, token, course_id, LECTURE_ONE, "lecture-01.txt")

        # The second lecture brings a new subject with it.
        llm.json_response = topics_payload("Congestion Control", "DNS Resolution")
        upload(client, token, course_id, LECTURE_TWO, "lecture-02.txt")

        topics = client.get(
            f"/api/v1/courses/{course_id}/topics", headers=auth(token)
        ).json()
        assert {t["name"] for t in topics} == {"Congestion Control", "DNS Resolution"}
        assert status(client, token, course_id)["topics_are_current"] is True

    def test_a_third_document_updates_again(
        self, client: TestClient, token: str, course_id: str, llm, automatic_topic_sync
    ) -> None:
        llm.json_response = topics_payload("Congestion Control")
        upload(client, token, course_id, LECTURE_ONE, "a.txt")
        llm.json_response = topics_payload("Congestion Control", "DNS Resolution")
        upload(client, token, course_id, LECTURE_TWO, "b.txt")
        llm.json_response = topics_payload(
            "Congestion Control", "DNS Resolution", "Fast Retransmit"
        )
        upload(client, token, course_id, LECTURE_ONE + b" Fast retransmit.", "c.txt")

        topics = client.get(
            f"/api/v1/courses/{course_id}/topics", headers=auth(token)
        ).json()
        assert len(topics) == 3

    def test_no_extraction_runs_when_topics_are_already_current(
        self, client: TestClient, token: str, course_id: str, llm, automatic_topic_sync
    ) -> None:
        """Reprocessing an unchanged document must not buy a second model call."""
        llm.json_response = topics_payload("Congestion Control")
        document = upload(client, token, course_id, LECTURE_ONE, "a.txt").json()
        after_first = llm.json_call_count

        # Reprocess: same content, so the fingerprint is unchanged.
        client.post(f"/api/v1/documents/{document['id']}/reprocess", headers=auth(token))
        assert llm.json_call_count == after_first


class TestLearningStateSurvives:
    """A topic update must never look like a course reset."""

    def test_mastery_survives_a_topic_update(
        self,
        client: TestClient,
        token: str,
        course_id: str,
        session: Session,
        llm,
        automatic_topic_sync,
    ) -> None:
        llm.json_response = topics_payload("Congestion Control")
        upload(client, token, course_id, LECTURE_ONE, "a.txt")

        topic = session.scalars(select(Topic).where(Topic.course_id == course_id)).one()
        user_id = session.scalar(select(Course.user_id).where(Course.id == course_id))
        session.add(
            TopicMastery(
                user_id=user_id,
                course_id=course_id,
                topic_id=topic.id,
                raw_score=64.0,
                mastery_score=57.0,
                questions_attempted=7,
                correct_answers=5,
            )
        )
        session.commit()

        # A second lecture triggers another extraction that keeps the same topic.
        llm.json_response = topics_payload("Congestion Control", "DNS Resolution")
        upload(client, token, course_id, LECTURE_TWO, "b.txt")

        session.expire_all()
        preserved = session.scalars(select(TopicMastery)).one()
        assert preserved.topic_id == topic.id, "the topic identity must be reused"
        assert preserved.raw_score == 64.0
        assert preserved.questions_attempted == 7

    def test_an_unchanged_topic_is_not_duplicated(
        self,
        client: TestClient,
        token: str,
        course_id: str,
        session: Session,
        llm,
        automatic_topic_sync,
    ) -> None:
        llm.json_response = topics_payload("Congestion Control")
        upload(client, token, course_id, LECTURE_ONE, "a.txt")
        llm.json_response = topics_payload("Congestion Control", "DNS Resolution")
        upload(client, token, course_id, LECTURE_TWO, "b.txt")

        session.expire_all()
        names = [
            t.normalised_name
            for t in session.scalars(select(Topic).where(Topic.course_id == course_id))
        ]
        assert len(names) == len(set(names)), f"duplicates: {names}"

    def test_a_dropped_topic_is_deactivated_not_deleted(
        self,
        client: TestClient,
        token: str,
        course_id: str,
        session: Session,
        llm,
        automatic_topic_sync,
    ) -> None:
        """Its mastery rows point at it, and deleting would destroy that history."""
        llm.json_response = topics_payload("Congestion Control", "Temporary Topic")
        upload(client, token, course_id, LECTURE_ONE, "a.txt")

        llm.json_response = topics_payload("Congestion Control")
        upload(client, token, course_id, LECTURE_TWO, "b.txt")

        session.expire_all()
        stored = {
            t.name: t.is_active
            for t in session.scalars(select(Topic).where(Topic.course_id == course_id))
        }
        assert stored.get("Temporary Topic") is False, "should be retired, not removed"
        assert stored.get("Congestion Control") is True


class TestFailuresAreSafe:
    def test_a_document_that_never_processes_triggers_no_extraction(
        self, client: TestClient, token: str, course_id: str, llm, automatic_topic_sync
    ) -> None:
        before = llm.json_call_count
        upload(client, token, course_id, b"", "empty.txt")
        assert llm.json_call_count == before

    def test_failed_extraction_leaves_the_document_ready(
        self, client: TestClient, token: str, course_id: str, llm, automatic_topic_sync
    ) -> None:
        """The document is committed READY before topics are attempted, so a topic
        failure cannot un-ready it."""
        llm.json_response = {"topics": "not a list"}
        upload(client, token, course_id, LECTURE_ONE, "a.txt")

        documents = wait_ready(client, token, course_id)
        assert documents[0]["processing_status"] == "ready"
        assert documents[0]["processing_error"] is None

    def test_failed_extraction_leaves_the_course_out_of_sync_and_retryable(
        self, client: TestClient, token: str, course_id: str, llm, automatic_topic_sync
    ) -> None:
        llm.json_response = {"topics": "not a list"}
        upload(client, token, course_id, LECTURE_ONE, "a.txt")
        assert status(client, token, course_id)["topics_are_current"] is False

        # The manual fallback then succeeds.
        llm.json_response = topics_payload("Congestion Control")
        retry = client.post(
            f"/api/v1/courses/{course_id}/topics/extract", headers=auth(token)
        )
        assert retry.status_code == 200
        assert status(client, token, course_id)["topics_are_current"] is True

    def test_failed_extraction_does_not_touch_existing_topics(
        self,
        client: TestClient,
        token: str,
        course_id: str,
        session: Session,
        llm,
        automatic_topic_sync,
    ) -> None:
        llm.json_response = topics_payload("Congestion Control")
        upload(client, token, course_id, LECTURE_ONE, "a.txt")

        llm.json_response = {"topics": "not a list"}
        upload(client, token, course_id, LECTURE_TWO, "b.txt")

        session.expire_all()
        survived = session.scalars(
            select(Topic).where(Topic.course_id == course_id)
        ).all()
        assert [t.name for t in survived] == ["Congestion Control"]
        assert survived[0].is_active is True


class TestConcurrency:
    def test_a_second_sync_is_skipped_rather_than_duplicated(
        self,
        client: TestClient,
        token: str,
        course_id: str,
        session: Session,
        llm,
    ) -> None:
        """`sync` re-checks under a non-blocking advisory lock, so a second caller
        finds the work already done instead of racing the unique constraint.

        A blocking `SELECT ... FOR UPDATE` would deadlock here: the fixture's
        transaction holds this course row open on another connection.
        """
        # Uploaded through the API so real chunks exist to extract from. Automatic
        # sync is off in this test, so the calls below are the only ones.
        upload(client, token, course_id, LECTURE_ONE, "a.txt")
        user_id = session.scalar(select(Course.user_id).where(Course.id == course_id))

        llm.json_response = topics_payload("Congestion Control")
        service = TopicService(session, llm)

        assert service.sync(user_id, course_id) is True
        calls_after_first = llm.json_call_count

        # Already current: returns without extracting, and without a second call.
        assert service.sync(user_id, course_id) is False
        assert llm.json_call_count == calls_after_first

    def test_sync_does_not_block_on_an_open_transaction(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        """The regression that hung the whole suite: a blocking row lock waits
        behind the fixture's own open transaction and never returns."""
        upload(client, token, course_id, LECTURE_ONE, "a.txt")
        user_id = session.scalar(select(Course.user_id).where(Course.id == course_id))
        llm.json_response = topics_payload("Congestion Control")

        # Completing at all is the assertion.
        TopicService(session, llm).sync(user_id, course_id)


class TestDerivedArtifacts:
    def test_new_material_marks_the_study_guide_stale(
        self, client: TestClient, token: str, course_id: str, llm, automatic_topic_sync
    ) -> None:
        """The guide's fingerprint covers documents and topics, so an automatic
        topic update is enough to flag it — no separate mechanism."""
        from app.tests.conftest import OVERVIEW_PAYLOAD, section_payload

        llm.json_response = topics_payload("Congestion Control")
        upload(client, token, course_id, LECTURE_ONE, "a.txt")

        llm.json_responses = [section_payload(), OVERVIEW_PAYLOAD]
        built = client.post(
            f"/api/v1/courses/{course_id}/study-guide", headers=auth(token)
        )
        assert built.status_code == 201
        assert built.json()["is_stale"] is False

        llm.json_response = topics_payload("Congestion Control", "DNS Resolution")
        upload(client, token, course_id, LECTURE_TWO, "b.txt")

        guide = client.get(
            f"/api/v1/courses/{course_id}/study-guide", headers=auth(token)
        ).json()
        assert guide["is_stale"] is True
        assert guide["sections"], "a stale guide stays readable"


class TestIsolation:
    def test_another_user_cannot_read_topic_sync_status(
        self, client: TestClient, token: str, other_token: str, course_id: str
    ) -> None:
        response = client.get(
            f"/api/v1/courses/{course_id}/topics/status", headers=auth(other_token)
        )
        assert response.status_code == 404

    def test_status_requires_authentication(
        self, client: TestClient, course_id: str
    ) -> None:
        assert client.get(f"/api/v1/courses/{course_id}/topics/status").status_code == 401

    def test_another_user_cannot_update_topics(
        self, client: TestClient, token: str, other_token: str, course_id: str
    ) -> None:
        response = client.post(
            f"/api/v1/courses/{course_id}/topics/extract", headers=auth(other_token)
        )
        assert response.status_code == 404


class TestManualFallbackUnchanged:
    def test_extract_still_reconciles_rather_than_wiping(
        self, client: TestClient, token: str, course_id: str, session: Session, llm
    ) -> None:
        """The manual action is the same service the automatic path uses."""
        upload(client, token, course_id, LECTURE_ONE, "a.txt")
        existing = make_topic(session, course_id, "Congestion Control", "Existing.")
        session.commit()

        llm.json_response = topics_payload("Congestion Control", "DNS Resolution")
        client.post(f"/api/v1/courses/{course_id}/topics/extract", headers=auth(token))

        session.expire_all()
        rows = session.scalars(select(Topic).where(Topic.course_id == course_id)).all()
        assert len(rows) == 2
        assert existing.id in {t.id for t in rows}, "identity reused, not replaced"
