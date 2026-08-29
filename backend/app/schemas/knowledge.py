"""Contracts for the knowledge map and gap detection."""

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models import RelationshipType
from app.schemas.common import ORMModel
from app.schemas.learning import SourceRef


class KnowledgeNodeRead(BaseModel):
    """One topic in the map, with the student's standing on it overlaid.

    Mastery is joined in at read time rather than stored on the graph: the map's
    structure comes from the material and does not change when a quiz is answered.
    """

    topic_id: uuid.UUID
    name: str
    description: str
    mastery: float
    effective_mastery: float
    band: str
    band_label: str
    questions_attempted: int


class KnowledgeEdgeRead(ORMModel):
    """One relationship, with the evidence behind it.

    `supporting_chunk_count` is a count of real excerpts, not a model-reported
    confidence. The UI says "supported by N excerpts" so the number means exactly
    what it is, and the sources are listed so the student can check.
    """

    id: uuid.UUID
    source_topic_id: uuid.UUID
    target_topic_id: uuid.UUID
    relationship_type: RelationshipType
    supporting_chunk_count: int
    sources: list[SourceRef]


class KnowledgeMapRead(BaseModel):
    course_id: uuid.UUID
    nodes: list[KnowledgeNodeRead]
    edges: list[KnowledgeEdgeRead]
    # Null until the map has been generated at least once.
    generated_at: datetime | None


class KnowledgeMapGenerateResponse(KnowledgeMapRead):
    """Adds what the generation run actually did, so the UI can explain a sparse
    map rather than leaving the student wondering."""

    candidates_rejected: int
    model_calls: int


class KnowledgeGapRead(BaseModel):
    """One detected gap.

    Produced by `services/learning/knowledge.py` from mastery and the graph. No
    language model is involved in deciding what the student does not know, and
    `reason` is assembled from the same facts as `severity` so the explanation
    cannot drift from the ranking.
    """

    topic_id: uuid.UUID
    name: str
    kind: str
    kind_label: str
    severity: float
    effective_mastery: float
    blocked_topics: list[str]
    attempted_dependents: list[str]
    reason: str


class KnowledgeGapsRead(BaseModel):
    course_id: uuid.UUID
    gaps: list[KnowledgeGapRead]
    # False when the map has never been generated: gap detection still works from
    # mastery alone, but without edges it cannot tell blocking from isolated.
    has_map: bool
