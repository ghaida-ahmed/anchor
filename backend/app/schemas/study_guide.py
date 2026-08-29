"""Contracts for the generated study guide."""

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models import StudyGuideStatus
from app.schemas.learning import SourceRef


class KeyTermRead(BaseModel):
    """A term the material itself defines, with the excerpt it was defined in."""

    term: str
    definition: str
    source: SourceRef | None


class StudyGuideSectionRead(BaseModel):
    """One topic's section, with the student's standing on that topic overlaid.

    The mastery fields are joined in on read. They are deliberately NOT baked into
    the generated text: the guide would be wrong the moment the student answered a
    question, and regenerating prose to update a badge would be absurd.
    """

    topic_id: uuid.UUID
    topic_name: str
    position: int
    summary: str
    key_concepts: list[str]
    sources: list[SourceRef]

    mastery: float
    effective_mastery: float
    band: str
    band_label: str
    # True when this section covers a topic the gap detector flagged, so the guide
    # can point the student at what to read first.
    is_knowledge_gap: bool


class StudyGuideRead(BaseModel):
    course_id: uuid.UUID
    status: StudyGuideStatus
    overview: str
    key_terms: list[KeyTermRead]
    sections: list[StudyGuideSectionRead]
    generated_at: datetime | None
    # Set only when status is FAILED, and safe to show to the student.
    error_message: str | None
    # Convenience for the UI banner: the material changed after generation.
    is_stale: bool
