"""Study guide endpoints.

GET reads the stored guide and never generates; POST generates and costs one model
call per topic plus one. A guide whose material has moved on comes back with status
STALE and `is_stale` true — readable, labelled, and regenerated only when asked.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import (
    CurrentUser,
    KnowledgeMapServiceDep,
    MasteryServiceDep,
    SessionDep,
    StudyGuideServiceDep,
)
from app.core.rate_limit import rate_limit_ai
from app.models import Document, DocumentChunk, StudyGuide, StudyGuideStatus
from app.schemas import KeyTermRead, SourceRef, StudyGuideRead, StudyGuideSectionRead
from app.services.learning.grounding import page_number_for
from app.services.learning.mastery import BAND_LABELS, band_for
from app.services.learning.retention import effective_mastery
from app.services.rag.retrieval import RetrievedChunk

router = APIRouter(tags=["study-guide"])

_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated."},
    status.HTTP_404_NOT_FOUND: {"description": "Not found for this user."},
    status.HTTP_400_BAD_REQUEST: {"description": "Not enough material."},
    status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "AI provider not configured."},
}


def _source_ref(session: Session, chunk_id, document_id) -> SourceRef | None:
    chunk = session.get(DocumentChunk, chunk_id)
    document = session.get(Document, document_id)
    if chunk is None or document is None:
        return None
    reference = RetrievedChunk(
        chunk_id=chunk.id,
        document_id=document.id,
        document_name=document.filename,
        page_number=chunk.page_number,
        chunk_index=chunk.chunk_index,
        content=chunk.content,
        similarity=1.0,
    )
    return SourceRef(
        document_id=document.id,
        document_name=document.filename,
        page_number=page_number_for(reference, document.file_type),
        chunk_id=chunk.id,
    )


def _render(
    session: Session,
    mastery: MasteryServiceDep,
    knowledge: KnowledgeMapServiceDep,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    guide: StudyGuide,
) -> StudyGuideRead:
    """Overlay the student's current standing on the stored text.

    The overlay is why the guide can be generated once and stay useful: the prose
    is about the material, the badges are about the student, and only the latter
    changes when they answer a question.
    """
    states = {topic.id: state for topic, state in mastery.for_course(user_id, course_id)}
    gap_topic_ids = {gap.topic_id for gap in knowledge.gaps(user_id, course_id)}

    sections: list[StudyGuideSectionRead] = []
    for section in guide.sections:
        state = states.get(section.topic_id)
        if state is None:
            # The topic was deactivated after generation. Its section is dropped
            # rather than shown against a topic the course no longer teaches.
            continue
        sections.append(
            StudyGuideSectionRead(
                topic_id=section.topic_id,
                topic_name=section.topic.name,
                position=section.position,
                summary=section.summary,
                key_concepts=[str(item) for item in section.key_concepts or []],
                sources=[
                    ref
                    for source in section.sources
                    if (ref := _source_ref(session, source.chunk_id, source.document_id))
                    is not None
                ],
                mastery=round(state.mastery_score, 1),
                effective_mastery=round(
                    effective_mastery(
                        state.mastery_score, state.evidence, state.last_practised_at
                    ),
                    1,
                ),
                band=band_for(state),
                band_label=BAND_LABELS[band_for(state)],
                is_knowledge_gap=section.topic_id in gap_topic_ids,
            )
        )

    key_terms = [
        KeyTermRead(
            term=str(term.get("term", "")),
            definition=str(term.get("definition", "")),
            source=_source_ref(session, term.get("chunk_id"), term.get("document_id")),
        )
        for term in guide.key_terms or []
        if isinstance(term, dict)
    ]

    return StudyGuideRead(
        course_id=course_id,
        status=guide.status,
        overview=guide.overview,
        key_terms=key_terms,
        sections=sections,
        generated_at=guide.generated_at,
        error_message=guide.error_message,
        is_stale=guide.status is StudyGuideStatus.STALE,
    )


@router.get(
    "/courses/{course_id}/study-guide",
    response_model=StudyGuideRead,
    responses=_RESPONSES,
    summary="Read the stored study guide",
)
def read_study_guide(
    service: StudyGuideServiceDep,
    knowledge: KnowledgeMapServiceDep,
    mastery: MasteryServiceDep,
    session: SessionDep,
    user: CurrentUser,
    course_id: uuid.UUID,
) -> StudyGuideRead:
    guide = service.get(user.id, course_id)
    if guide is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No study guide has been generated for this course yet.",
        )
    return _render(session, mastery, knowledge, user.id, course_id, guide)


@router.post(
    "/courses/{course_id}/study-guide",
    dependencies=[Depends(rate_limit_ai)],
    response_model=StudyGuideRead,
    status_code=status.HTTP_201_CREATED,
    responses=_RESPONSES,
    summary="Generate or regenerate the study guide",
)
def generate_study_guide(
    service: StudyGuideServiceDep,
    knowledge: KnowledgeMapServiceDep,
    mastery: MasteryServiceDep,
    session: SessionDep,
    user: CurrentUser,
    course_id: uuid.UUID,
) -> StudyGuideRead:
    guide = service.generate(user.id, course_id)
    return _render(session, mastery, knowledge, user.id, course_id, guide)
