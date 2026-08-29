"""The knowledge map: candidate generation, validation, cycles, and gap detection.

Two things are load-bearing here. First, an edge cannot exist without evidence that
resolves to a real chunk of this course's material. Second, gap detection never
consults a model — the tests prove it by asserting the call count stays flat.
"""

import io
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RelationshipType, TopicRelationship, TopicRelationshipEvidence
from app.services.learning.knowledge import (
    BLOCKING,
    GAP_THRESHOLD,
    ISOLATED,
    UNMET_PREREQUISITE,
    TopicNode,
    dependents_of,
    detect_gaps,
)
from app.tests.conftest import auth, make_topic, relationship_payload

# Two topics the same passage genuinely discusses together, so the lexical test
# embedder retrieves overlapping chunks for both.
NOTES = (
    b"Slow start doubles the congestion window every round trip until a loss "
    b"occurs. Congestion avoidance then takes over, growing the congestion window "
    b"additively. Both phases operate on the same congestion window, and slow "
    b"start must be understood before congestion avoidance makes sense."
)

SLOW_START = "Slow Start"
SLOW_START_DESCRIPTION = (
    "Doubling the congestion window every round trip until a loss occurs."
)
AVOIDANCE = "Congestion Avoidance"
AVOIDANCE_DESCRIPTION = "Growing the congestion window additively after slow start ends."


def ground(client: TestClient, token: str, course_id: str, session: Session):
    response = client.post(
        f"/api/v1/courses/{course_id}/documents",
        files={"file": ("notes.txt", io.BytesIO(NOTES), "text/plain")},
        headers=auth(token),
    )
    assert response.status_code == 201
    first = make_topic(session, course_id, SLOW_START, SLOW_START_DESCRIPTION)
    second = make_topic(session, course_id, AVOIDANCE, AVOIDANCE_DESCRIPTION)
    session.flush()
    return first, second


def build(client, token, course_id):
    return client.post(f"/api/v1/courses/{course_id}/knowledge-map", headers=auth(token))


class TestGeneration:
    def test_a_prerequisite_edge_is_stored_with_its_evidence(
        self, client, token, course_id, session, llm
    ) -> None:
        ground(client, token, course_id, session)
        llm.json_response = relationship_payload((1, "prerequisite", "a", [1]))

        response = build(client, token, course_id)
        assert response.status_code == 201, response.text
        body = response.json()

        assert len(body["edges"]) == 1
        edge = body["edges"][0]
        assert edge["relationship_type"] == "prerequisite"
        assert edge["supporting_chunk_count"] == 1
        # The count is a count of excerpts we actually hold, and they render as
        # citations the student can check.
        assert len(edge["sources"]) == 1
        assert edge["sources"][0]["document_name"] == "notes.txt"

        evidence = list(session.scalars(select(TopicRelationshipEvidence)))
        assert len(evidence) == 1

    def test_candidate_pairs_are_batched_not_asked_one_by_one(
        self, client, token, course_id, session, llm
    ) -> None:
        """Two topics is one pair, and one pair is one call — not one per ordering."""
        ground(client, token, course_id, session)
        llm.json_response = relationship_payload((1, "related", "none", [1]))

        body = build(client, token, course_id).json()
        assert body["model_calls"] == 1

    def test_a_related_edge_is_stored_in_one_canonical_direction(
        self, client, token, course_id, session, llm
    ) -> None:
        ground(client, token, course_id, session)
        llm.json_response = relationship_payload((1, "related", "none", [1]))
        build(client, token, course_id)

        edges = list(session.scalars(select(TopicRelationship)))
        assert len(edges) == 1
        # Canonical ordering is what makes the reverse duplicate impossible.
        assert edges[0].source_topic_id.hex < edges[0].target_topic_id.hex

    def test_regenerating_replaces_rather_than_duplicates(
        self, client, token, course_id, session, llm
    ) -> None:
        ground(client, token, course_id, session)
        llm.json_response = relationship_payload((1, "related", "none", [1]))
        build(client, token, course_id)
        build(client, token, course_id)

        session.expire_all()
        assert len(list(session.scalars(select(TopicRelationship)))) == 1

    def test_a_single_topic_course_cannot_have_a_map(
        self, client, token, course_id, session, llm
    ) -> None:
        client.post(
            f"/api/v1/courses/{course_id}/documents",
            files={"file": ("notes.txt", io.BytesIO(NOTES), "text/plain")},
            headers=auth(token),
        )
        make_topic(session, course_id, SLOW_START, SLOW_START_DESCRIPTION)
        session.flush()
        assert build(client, token, course_id).status_code == 400


class TestValidation:
    def test_a_relationship_of_none_produces_no_edge(
        self, client, token, course_id, session, llm
    ) -> None:
        """Co-occurrence is not a relationship, and the model is allowed to say so."""
        ground(client, token, course_id, session)
        llm.json_response = relationship_payload((1, "none", "none", [1]))

        body = build(client, token, course_id).json()
        assert body["edges"] == []
        assert body["candidates_rejected"] == 1

    def test_an_edge_without_resolvable_evidence_is_dropped(
        self, client, token, course_id, session, llm
    ) -> None:
        ground(client, token, course_id, session)
        # Excerpt 99 was never supplied.
        llm.json_response = relationship_payload((1, "prerequisite", "a", [99]))

        body = build(client, token, course_id).json()
        assert body["edges"] == []

    def test_a_prerequisite_without_a_direction_is_dropped(
        self, client, token, course_id, session, llm
    ) -> None:
        """Claiming a dependency but not which way round is not a prerequisite;
        guessing the direction would be worse than dropping the edge."""
        ground(client, token, course_id, session)
        llm.json_response = relationship_payload((1, "prerequisite", "none", [1]))

        assert build(client, token, course_id).json()["edges"] == []

    def test_an_unknown_pair_index_is_ignored(
        self, client, token, course_id, session, llm
    ) -> None:
        ground(client, token, course_id, session)
        llm.json_response = relationship_payload((42, "prerequisite", "a", [1]))

        assert build(client, token, course_id).json()["edges"] == []

    def test_the_same_pair_answered_twice_yields_one_edge(
        self, client, token, course_id, session, llm
    ) -> None:
        ground(client, token, course_id, session)
        llm.json_response = relationship_payload(
            (1, "prerequisite", "a", [1]), (1, "related", "none", [1])
        )
        assert len(build(client, token, course_id).json()["edges"]) == 1

    def test_a_malformed_response_leaves_the_map_empty(
        self, client, token, course_id, session, llm
    ) -> None:
        ground(client, token, course_id, session)
        llm.json_response = {"relationships": "not a list"}
        assert build(client, token, course_id).json()["edges"] == []


class TestCycles:
    """Prerequisite edges must form a DAG, or no study order exists."""

    def test_a_direct_reverse_edge_is_rejected(self) -> None:
        from app.services.learning.knowledge_service import (
            KnowledgeMapService,
            ProposedEdge,
        )

        a, b = uuid.uuid4(), uuid.uuid4()
        closure: dict = {}
        forward = ProposedEdge(a, b, RelationshipType.PREREQUISITE, [])
        assert not KnowledgeMapService._would_cycle(forward, closure)
        KnowledgeMapService._record_prerequisite(forward, closure)

        backward = ProposedEdge(b, a, RelationshipType.PREREQUISITE, [])
        assert KnowledgeMapService._would_cycle(backward, closure)

    def test_a_transitive_cycle_is_rejected(self) -> None:
        from app.services.learning.knowledge_service import (
            KnowledgeMapService,
            ProposedEdge,
        )

        a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        closure: dict = {}
        for source, target in ((a, b), (b, c)):
            edge = ProposedEdge(source, target, RelationshipType.PREREQUISITE, [])
            assert not KnowledgeMapService._would_cycle(edge, closure)
            KnowledgeMapService._record_prerequisite(edge, closure)

        closing = ProposedEdge(c, a, RelationshipType.PREREQUISITE, [])
        assert KnowledgeMapService._would_cycle(closing, closure)

    def test_a_shortcut_along_a_chain_is_not_a_cycle(self) -> None:
        from app.services.learning.knowledge_service import (
            KnowledgeMapService,
            ProposedEdge,
        )

        a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        closure: dict = {}
        for source, target in ((a, b), (b, c)):
            edge = ProposedEdge(source, target, RelationshipType.PREREQUISITE, [])
            KnowledgeMapService._record_prerequisite(edge, closure)

        shortcut = ProposedEdge(a, c, RelationshipType.PREREQUISITE, [])
        assert not KnowledgeMapService._would_cycle(shortcut, closure)

    def test_related_edges_are_never_cycle_checked(self) -> None:
        from app.services.learning.knowledge_service import (
            KnowledgeMapService,
            ProposedEdge,
        )

        a, b = uuid.uuid4(), uuid.uuid4()
        edge = ProposedEdge(a, b, RelationshipType.RELATED, [])
        assert not KnowledgeMapService._would_cycle(edge, {b: {a}})


class TestGapDetection:
    """Deterministic. `detect_gaps` is a pure function and gets tested as one."""

    def _nodes(self, *specs):
        return [
            TopicNode(topic_id=tid, name=name, effective_mastery=mastery, evidence=ev)
            for tid, name, mastery, ev in specs
        ]

    def test_a_weak_topic_blocking_an_attempted_one_ranks_highest(self) -> None:
        base, built = uuid.uuid4(), uuid.uuid4()
        gaps = detect_gaps(
            self._nodes((base, "Slow Start", 20.0, 4.0), (built, "Avoidance", 50.0, 6.0)),
            [(base, built)],
        )
        assert gaps[0].topic_id == base
        assert gaps[0].kind == UNMET_PREREQUISITE
        assert "Avoidance" in gaps[0].attempted_dependents
        assert "Avoidance" in gaps[0].reason

    def test_a_weak_topic_with_untouched_dependents_is_blocking(self) -> None:
        base, later = uuid.uuid4(), uuid.uuid4()
        gaps = detect_gaps(
            self._nodes((base, "Slow Start", 20.0, 4.0), (later, "Avoidance", 0.0, 0.0)),
            [(base, later)],
        )
        assert [gap.kind for gap in gaps if gap.topic_id == base] == [BLOCKING]

    def test_a_weak_topic_with_no_dependents_is_isolated(self) -> None:
        lone = uuid.uuid4()
        gaps = detect_gaps(self._nodes((lone, "DNS", 20.0, 4.0)), [])
        assert gaps[0].kind == ISOLATED

    def test_an_untouched_topic_with_no_attempted_dependents_is_not_a_gap(
        self,
    ) -> None:
        """Not having reached a topic is not a failure at it."""
        fresh = uuid.uuid4()
        assert detect_gaps(self._nodes((fresh, "Unseen", 0.0, 0.0)), []) == []

    def test_a_strong_topic_is_never_a_gap(self) -> None:
        strong = uuid.uuid4()
        assert detect_gaps(self._nodes((strong, "Solid", GAP_THRESHOLD, 10.0)), []) == []

    def test_severity_rises_with_the_number_of_dependents(self) -> None:
        one, two = uuid.uuid4(), uuid.uuid4()
        deps = [uuid.uuid4() for _ in range(3)]
        nodes = self._nodes(
            (one, "One", 20.0, 4.0),
            (two, "Two", 20.0, 4.0),
            *[(d, f"D{i}", 90.0, 5.0) for i, d in enumerate(deps)],
        )
        gaps = {
            gap.topic_id: gap
            for gap in detect_gaps(nodes, [(two, deps[0]), (two, deps[1])], limit=10)
        }
        assert gaps[two].severity > gaps[one].severity

    def test_the_ordering_is_stable(self) -> None:
        a, b = uuid.uuid4(), uuid.uuid4()
        nodes = self._nodes((a, "Alpha", 20.0, 4.0), (b, "Beta", 20.0, 4.0))
        first = [gap.name for gap in detect_gaps(nodes, [])]
        second = [gap.name for gap in detect_gaps(list(reversed(nodes)), [])]
        assert first == second == ["Alpha", "Beta"]

    def test_transitive_dependents_are_counted(self) -> None:
        a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        assert dependents_of(a, [(a, b), (b, c)]) == [b, c]

    def test_dependent_traversal_terminates_on_a_cycle(self) -> None:
        """Defence in depth: cycles are rejected at write time, but a graph that
        somehow reached the database must not hang the reader."""
        a, b = uuid.uuid4(), uuid.uuid4()
        assert dependents_of(a, [(a, b), (b, a)]) == [b]


class TestGapsEndpoint:
    def test_gap_detection_makes_no_model_calls(
        self, client, token, course_id, session, llm
    ) -> None:
        ground(client, token, course_id, session)
        llm.json_response = relationship_payload((1, "prerequisite", "a", [1]))
        build(client, token, course_id)

        before = llm.json_call_count
        response = client.get(
            f"/api/v1/courses/{course_id}/knowledge-gaps", headers=auth(token)
        )
        assert response.status_code == 200
        assert llm.json_call_count == before

    def test_gaps_work_without_a_map(
        self, client, token, course_id, session, llm
    ) -> None:
        ground(client, token, course_id, session)
        response = client.get(
            f"/api/v1/courses/{course_id}/knowledge-gaps", headers=auth(token)
        )
        assert response.status_code == 200
        assert response.json()["has_map"] is False


class TestIsolation:
    def test_reading_never_generates(
        self, client, token, course_id, session, llm
    ) -> None:
        ground(client, token, course_id, session)
        before = llm.json_call_count
        response = client.get(
            f"/api/v1/courses/{course_id}/knowledge-map", headers=auth(token)
        )
        assert response.status_code == 200
        assert response.json()["edges"] == []
        assert llm.json_call_count == before

    def test_another_user_cannot_read_this_map(
        self, client, token, other_token, course_id, session, llm
    ) -> None:
        ground(client, token, course_id, session)
        response = client.get(
            f"/api/v1/courses/{course_id}/knowledge-map", headers=auth(other_token)
        )
        assert response.status_code == 404

    def test_another_user_cannot_generate_this_map(
        self, client, token, other_token, course_id, session, llm
    ) -> None:
        ground(client, token, course_id, session)
        assert build(client, other_token, course_id).status_code == 404
