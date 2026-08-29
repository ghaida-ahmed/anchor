"""Building and reading a course's knowledge map.

The map is a graph whose nodes are the course's topics and whose edges say either
"this must be learned first" (prerequisite) or "these belong together" (related).

HOW EDGES ARE PROPOSED WITHOUT ASKING ABOUT EVERY PAIR
======================================================

Asking the model about all pairs is O(n^2): 25 topics is 300 calls, which is both
slow and a real cost. Instead the *candidates* are found deterministically, and the
model only judges a shortlist.

    1. retrieve each topic's top chunks (the existing ownership-scoped search)
    2. a pair is a candidate only if the two topics share at least one chunk —
       the material physically discusses them in the same place
    3. rank candidates by how many chunks they share, cap at MAX_CANDIDATE_PAIRS
    4. judge PAIRS_PER_CALL at a time, grounded in the shared chunks

Ten topics typically yield ~15 candidates, so two calls rather than 45.

Sharing a chunk is evidence of *proximity*, not of a relationship — plenty of
neighbouring topics have nothing to do with each other. That judgement is what the
model is for, and the prompt tells it explicitly that co-occurrence alone is not
enough.

CONFIDENCE
==========

`supporting_chunk_count` is the number of real chunks cited for an edge. It is a
count of evidence we hold, not a probability the model reported: a model's stated
confidence is unverifiable, whereas "three excerpts support this" is something the
student can click through and check. The UI phrases it exactly that way.

CYCLES
======

"A is a prerequisite of B" and "B is a prerequisite of A" cannot both be true, and
a cycle would make any study order impossible. Edges are therefore accepted one at
a time, and an edge that would close a cycle is rejected rather than stored. The
first edge wins, which is why candidates are processed in a deterministic order:
better-evidenced pairs are judged first, so the edge that survives is the one with
more support behind it.
"""

import uuid
from dataclasses import dataclass
from itertools import combinations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.exceptions import ResourceNotFoundError
from app.models import (
    Course,
    RelationshipType,
    Topic,
    TopicRelationship,
    TopicRelationshipEvidence,
)
from app.services.learning.grounding import (
    GroundingContext,
    InsufficientMaterialError,
    build_grounding_context,
)
from app.services.learning.knowledge import KnowledgeGap, TopicNode, detect_gaps
from app.services.learning.mastery_service import MasteryService
from app.services.learning.prompts import (
    RELATIONSHIP_SCHEMA,
    RELATIONSHIP_SYSTEM,
    relationship_prompt,
)
from app.services.rag.embeddings import EmbeddingProvider
from app.services.rag.generation import ChatMessage, GenerationError, LLMProvider
from app.services.rag.retrieval import RetrievalService, RetrievedChunk

# Chunks pulled per topic when looking for overlap. Wider than quiz generation's
# window: overlap is the whole point here, and a narrow window finds none.
CHUNKS_PER_TOPIC = 10

# A course needs at least two topics before "relationship" means anything.
MIN_TOPICS_FOR_MAP = 2

# Ceiling on candidates judged, which is also the ceiling on model calls:
# MAX_CANDIDATE_PAIRS / PAIRS_PER_CALL, rounded up.
MAX_CANDIDATE_PAIRS = 30
PAIRS_PER_CALL = 8

# Excerpts one batch may carry. Shared chunks repeat across pairs, so the union is
# usually far smaller than pairs x chunks.
MAX_EXCERPTS_PER_CALL = 24


@dataclass(frozen=True)
class CandidatePair:
    """Two topics the material discusses in the same place."""

    a: Topic
    b: Topic
    shared: list[RetrievedChunk]

    @property
    def strength(self) -> int:
        return len(self.shared)


@dataclass(frozen=True)
class ProposedEdge:
    source_id: uuid.UUID  # prerequisite, or the lower-sorted topic when related
    target_id: uuid.UUID
    relationship: RelationshipType
    evidence: list[RetrievedChunk]


@dataclass(frozen=True)
class KnowledgeMapResult:
    topics: list[Topic]
    relationships: list[TopicRelationship]
    # Candidates that were judged but produced no edge — reported so the summary
    # can say the map is sparse because the material is, not because it failed.
    rejected_count: int
    model_calls: int


class KnowledgeMapService:
    def __init__(
        self, session: Session, embeddings: EmbeddingProvider, llm: LLMProvider
    ) -> None:
        self.session = session
        self.embeddings = embeddings
        self.llm = llm
        self.retrieval = RetrievalService(session)
        self.mastery = MasteryService(session)

    # --- Reading ---------------------------------------------------------------

    def get(
        self, user_id: uuid.UUID, course_id: uuid.UUID
    ) -> tuple[list[Topic], list[TopicRelationship]]:
        """The stored map. Never generates: generation costs money and the caller
        decides when to spend it."""
        self._assert_course_owned(user_id, course_id)

        topics = list(
            self.session.scalars(
                select(Topic)
                .where(Topic.course_id == course_id, Topic.is_active.is_(True))
                .order_by(Topic.name)
            )
        )
        relationships = list(
            self.session.scalars(
                select(TopicRelationship)
                .where(TopicRelationship.course_id == course_id)
                .options(selectinload(TopicRelationship.evidence))
                .order_by(TopicRelationship.supporting_chunk_count.desc())
            )
        )
        # An edge to a topic that has since been deactivated would render as a
        # dangling node, so it is filtered out of the view rather than deleted —
        # reactivating the topic brings its edges straight back.
        active = {topic.id for topic in topics}
        relationships = [
            edge
            for edge in relationships
            if edge.source_topic_id in active and edge.target_topic_id in active
        ]
        return topics, relationships

    def gaps(self, user_id: uuid.UUID, course_id: uuid.UUID) -> list[KnowledgeGap]:
        """Deterministic gap detection over the stored graph.

        The model is not consulted here at all — see `knowledge.py`.
        """
        _, relationships = self.get(user_id, course_id)
        candidates = self.mastery.candidates_for(user_id, course_id)

        nodes = [
            TopicNode(
                topic_id=candidate.topic_id,
                name=candidate.name,
                effective_mastery=candidate.effective_mastery,
                evidence=candidate.state.evidence,
            )
            for candidate in candidates
        ]
        edges = [
            (edge.source_topic_id, edge.target_topic_id)
            for edge in relationships
            if edge.relationship_type is RelationshipType.PREREQUISITE
        ]
        return detect_gaps(nodes, edges)

    # --- Generation ------------------------------------------------------------

    def generate(self, user_id: uuid.UUID, course_id: uuid.UUID) -> KnowledgeMapResult:
        """(Re)derive the course's topic graph from its material."""
        course = self._assert_course_owned(user_id, course_id)

        topics = list(
            self.session.scalars(
                select(Topic)
                .where(Topic.course_id == course_id, Topic.is_active.is_(True))
                .order_by(Topic.name)
            )
        )
        if len(topics) < MIN_TOPICS_FOR_MAP:
            raise InsufficientMaterialError(
                "A knowledge map needs at least two topics. Upload more material and "
                "extract topics first."
            )

        candidates = self._find_candidates(user_id, course_id, topics)
        if not candidates:
            raise InsufficientMaterialError(
                "No two topics share any course material, so there is nothing to "
                "relate. This usually means the documents cover separate subjects."
            )

        by_id = {topic.id: topic for topic in topics}
        accepted: list[ProposedEdge] = []
        # Reachability over accepted prerequisite edges, for cycle rejection.
        prerequisites: dict[uuid.UUID, set[uuid.UUID]] = {}
        judged = 0
        calls = 0

        for start in range(0, len(candidates), PAIRS_PER_CALL):
            batch = candidates[start : start + PAIRS_PER_CALL]
            judged += len(batch)
            calls += 1
            for edge in self._judge(course.title, batch, by_id):
                if self._would_cycle(edge, prerequisites):
                    continue
                accepted.append(edge)
                if edge.relationship is RelationshipType.PREREQUISITE:
                    self._record_prerequisite(edge, prerequisites)

        relationships = self._persist(course_id, accepted)
        return KnowledgeMapResult(
            topics=topics,
            relationships=relationships,
            rejected_count=judged - len(accepted),
            model_calls=calls,
        )

    # --- Candidate generation --------------------------------------------------

    def _find_candidates(
        self, user_id: uuid.UUID, course_id: uuid.UUID, topics: list[Topic]
    ) -> list[CandidatePair]:
        """Pairs of topics the material discusses in the same chunks.

        One embedding call per topic, no model calls, and the result is ordered
        deterministically so a regeneration judges the same pairs in the same order.
        """
        chunks_by_topic: dict[uuid.UUID, dict[uuid.UUID, RetrievedChunk]] = {}

        for topic in topics:
            query = f"{topic.name}. {topic.description}".strip()
            found = self.retrieval.search(
                user_id,
                course_id,
                self.embeddings.embed_query(query),
                top_k=CHUNKS_PER_TOPIC,
                min_similarity=settings.RAG_MIN_SIMILARITY,
            )
            chunks_by_topic[topic.id] = {chunk.chunk_id: chunk for chunk in found}

        candidates: list[CandidatePair] = []
        for first, second in combinations(topics, 2):
            left = chunks_by_topic[first.id]
            shared_ids = left.keys() & chunks_by_topic[second.id].keys()
            if not shared_ids:
                continue
            # Ordered by chunk_index so excerpts read in the material's own order.
            shared = sorted(
                (left[chunk_id] for chunk_id in shared_ids),
                key=lambda chunk: (chunk.document_id.hex, chunk.chunk_index),
            )
            candidates.append(CandidatePair(a=first, b=second, shared=shared))

        candidates.sort(key=lambda pair: (-pair.strength, pair.a.name, pair.b.name))
        return candidates[:MAX_CANDIDATE_PAIRS]

    # --- Classification --------------------------------------------------------

    def _judge(
        self,
        course_title: str,
        batch: list[CandidatePair],
        by_id: dict[uuid.UUID, Topic],
    ) -> list[ProposedEdge]:
        """Ask the model about one batch of pairs, then validate every answer."""
        excerpts: list[RetrievedChunk] = []
        numbers: dict[uuid.UUID, int] = {}
        for pair in batch:
            for chunk in pair.shared:
                if chunk.chunk_id in numbers or len(excerpts) >= MAX_EXCERPTS_PER_CALL:
                    continue
                excerpts.append(chunk)
                numbers[chunk.chunk_id] = len(excerpts)

        context = build_grounding_context(excerpts)
        # build_grounding_context may drop trailing excerpts to fit its char budget,
        # so the authoritative numbering is whatever it actually kept.
        kept = {chunk.chunk_id for chunk in context.chunks}

        lines: list[str] = []
        allowed: dict[int, set[int]] = {}
        for index, pair in enumerate(batch, start=1):
            shared_numbers = sorted(
                numbers[chunk.chunk_id] for chunk in pair.shared if chunk.chunk_id in kept
            )
            if not shared_numbers:
                continue
            allowed[index] = set(shared_numbers)
            lines.append(
                f"Pair {index}:\n"
                f"  a = {pair.a.name}"
                + (f" — {pair.a.description}" if pair.a.description else "")
                + f"\n  b = {pair.b.name}"
                + (f" — {pair.b.description}" if pair.b.description else "")
                + f"\n  shared excerpts: {', '.join(str(n) for n in shared_numbers)}"
            )

        if not lines:
            return []

        try:
            raw = self.llm.generate_json(
                [
                    ChatMessage(role="system", content=RELATIONSHIP_SYSTEM),
                    ChatMessage(
                        role="user",
                        content=relationship_prompt(
                            course_title, "\n\n".join(lines), context.text
                        ),
                    ),
                ],
                RELATIONSHIP_SCHEMA,
            )
        except GenerationError:
            # One failed batch should not lose the batches that succeeded. The map
            # is simply sparser, and the caller's summary reports how many pairs
            # produced nothing.
            return []

        return self._validate(raw, batch, allowed, context, by_id)

    def _validate(
        self,
        raw: object,
        batch: list[CandidatePair],
        allowed: dict[int, set[int]],
        context: GroundingContext,
        by_id: dict[uuid.UUID, Topic],
    ) -> list[ProposedEdge]:
        """Reject everything a schema cannot catch.

        The load-bearing check is the last one: evidence must be a chunk WE supplied
        for THIS pair. That makes it impossible for an edge to be stored citing
        material that does not mention both topics.
        """
        if not isinstance(raw, dict):
            return []
        items = raw.get("relationships")
        if not isinstance(items, list):
            return []

        edges: list[ProposedEdge] = []
        seen_pairs: set[int] = set()

        for item in items:
            if not isinstance(item, dict):
                continue

            index = item.get("pair_index")
            if not isinstance(index, int) or index not in allowed:
                continue
            # A model that answers the same pair twice gets its first answer used.
            if index in seen_pairs:
                continue

            kind = str(item.get("relationship") or "").strip().lower()
            if kind not in ("prerequisite", "related"):
                continue

            pair = batch[index - 1]
            if pair.a.id == pair.b.id or pair.a.id not in by_id or pair.b.id not in by_id:
                continue

            numbers = item.get("excerpt_numbers")
            if not isinstance(numbers, list):
                continue

            evidence: list[RetrievedChunk] = []
            seen_chunks: set[uuid.UUID] = set()
            for number in numbers:
                if not isinstance(number, int) or number not in allowed[index]:
                    continue
                chunk = context.resolve(number)
                if chunk is None or chunk.chunk_id in seen_chunks:
                    continue
                seen_chunks.add(chunk.chunk_id)
                evidence.append(chunk)

            # No verifiable evidence, no edge. This is the whole guarantee.
            if not evidence:
                continue

            if kind == "prerequisite":
                side = str(item.get("prerequisite_topic") or "").strip().lower()
                if side == "a":
                    source, target = pair.a, pair.b
                elif side == "b":
                    source, target = pair.b, pair.a
                else:
                    # Claimed a dependency but could not say which way round; that
                    # is not a prerequisite, and guessing a direction would be worse
                    # than dropping it.
                    continue
                relationship = RelationshipType.PREREQUISITE
            else:
                # Related edges are undirected. Storing them in a canonical order
                # means the reverse duplicate cannot exist, enforced by the unique
                # constraint rather than by hoping the model is consistent.
                source, target = (
                    (pair.a, pair.b)
                    if pair.a.id.hex < pair.b.id.hex
                    else (pair.b, pair.a)
                )
                relationship = RelationshipType.RELATED

            seen_pairs.add(index)
            edges.append(
                ProposedEdge(
                    source_id=source.id,
                    target_id=target.id,
                    relationship=relationship,
                    evidence=evidence,
                )
            )

        return edges

    # --- Cycles ----------------------------------------------------------------

    @staticmethod
    def _record_prerequisite(
        edge: ProposedEdge, prerequisites: dict[uuid.UUID, set[uuid.UUID]]
    ) -> None:
        """Maintain the transitive closure of "must be learned before".

        `prerequisites[t]` holds every topic that must come before `t`. Kept as a
        closure so the cycle check is a set lookup rather than a graph walk.
        """
        ancestors = prerequisites.setdefault(edge.target_id, set())
        ancestors.add(edge.source_id)
        ancestors |= prerequisites.get(edge.source_id, set())

        for target, existing in prerequisites.items():
            if edge.target_id in existing and target != edge.target_id:
                existing |= ancestors

    @staticmethod
    def _would_cycle(
        edge: ProposedEdge, prerequisites: dict[uuid.UUID, set[uuid.UUID]]
    ) -> bool:
        if edge.relationship is not RelationshipType.PREREQUISITE:
            return False
        # Adding source -> target closes a cycle if target already comes before
        # source, i.e. target is among source's ancestors. Testing the other
        # direction would only catch an edge that is already stored.
        return edge.source_id == edge.target_id or edge.target_id in prerequisites.get(
            edge.source_id, set()
        )

    # --- Persistence -----------------------------------------------------------

    def _persist(
        self, course_id: uuid.UUID, edges: list[ProposedEdge]
    ) -> list[TopicRelationship]:
        """Replace the course's map in one transaction.

        A full replace is safe here in a way it would not be for topics: an edge
        carries no student history, only derived structure, so regenerating loses
        nothing. Deletion cascades to the evidence rows.
        """
        self.session.execute(
            delete(TopicRelationship).where(TopicRelationship.course_id == course_id)
        )

        stored: list[TopicRelationship] = []
        for edge in edges:
            relationship = TopicRelationship(
                course_id=course_id,
                source_topic_id=edge.source_id,
                target_topic_id=edge.target_id,
                relationship_type=edge.relationship,
                supporting_chunk_count=len(edge.evidence),
            )
            relationship.evidence = [
                TopicRelationshipEvidence(
                    chunk_id=chunk.chunk_id, document_id=chunk.document_id
                )
                for chunk in edge.evidence
            ]
            self.session.add(relationship)
            stored.append(relationship)

        self.session.commit()
        for relationship in stored:
            self.session.refresh(relationship)
        return stored

    def _assert_course_owned(self, user_id: uuid.UUID, course_id: uuid.UUID) -> Course:
        course = self.session.scalar(
            select(Course).where(Course.id == course_id, Course.user_id == user_id)
        )
        if course is None:
            raise ResourceNotFoundError("Course", str(course_id))
        return course
