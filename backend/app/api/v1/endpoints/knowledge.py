"""Knowledge map and knowledge-gap endpoints.

Generation is a POST because it costs model calls; reading is a GET and never
generates. A student who opens the tab on a course with no map sees an empty map
and a button, not a surprise bill.
"""

import uuid

from fastapi import APIRouter, status
from sqlalchemy.orm import Session

from app.api.deps import (
    CurrentUser,
    KnowledgeMapServiceDep,
    MasteryServiceDep,
    SessionDep,
)
from app.models import Document, DocumentChunk, TopicRelationship
from app.schemas import (
    KnowledgeEdgeRead,
    KnowledgeGapRead,
    KnowledgeGapsRead,
    KnowledgeMapGenerateResponse,
    KnowledgeMapRead,
    KnowledgeNodeRead,
    SourceRef,
)
from app.services.learning.grounding import page_number_for
from app.services.learning.knowledge import GAP_KIND_LABELS
from app.services.learning.mastery import BAND_LABELS, band_for
from app.services.learning.retention import effective_mastery
from app.services.rag.retrieval import RetrievedChunk

router = APIRouter(tags=["knowledge-map"])

_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated."},
    status.HTTP_404_NOT_FOUND: {"description": "Not found for this user."},
    status.HTTP_400_BAD_REQUEST: {"description": "Not enough material."},
    status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "AI provider not configured."},
}


def _sources_for(session: Session, edge: TopicRelationship) -> list[SourceRef]:
    """Resolve an edge's evidence rows to citations.

    Read from the chunk and document rows at render time, so a renamed file stays
    correct and a page number can never have been invented.
    """
    sources: list[SourceRef] = []
    for evidence in edge.evidence:
        chunk = session.get(DocumentChunk, evidence.chunk_id)
        document = session.get(Document, evidence.document_id)
        if chunk is None or document is None:
            # Source deleted since generation. Better no citation than a dangling
            # one; the count shown alongside is the number we can still show.
            continue
        reference = RetrievedChunk(
            chunk_id=chunk.id,
            document_id=document.id,
            document_name=document.filename,
            page_number=chunk.page_number,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
            similarity=1.0,
        )
        sources.append(
            SourceRef(
                document_id=document.id,
                document_name=document.filename,
                page_number=page_number_for(reference, document.file_type),
                chunk_id=chunk.id,
            )
        )
    return sources


def _render_map(
    session: Session,
    mastery: MasteryServiceDep,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    topics,
    edges,
) -> tuple[list[KnowledgeNodeRead], list[KnowledgeEdgeRead]]:
    """Join the graph to the student's mastery for display."""
    states = {topic.id: state for topic, state in mastery.for_course(user_id, course_id)}
    by_id = {topic.id: topic for topic in topics}

    nodes: list[KnowledgeNodeRead] = []
    for topic in topics:
        state = states.get(topic.id)
        if state is None:
            continue
        nodes.append(
            KnowledgeNodeRead(
                topic_id=topic.id,
                name=topic.name,
                description=topic.description,
                mastery=round(state.mastery_score, 1),
                effective_mastery=round(
                    effective_mastery(
                        state.mastery_score, state.evidence, state.last_practised_at
                    ),
                    1,
                ),
                band=band_for(state),
                band_label=BAND_LABELS[band_for(state)],
                questions_attempted=state.questions_attempted,
            )
        )

    rendered_edges = [
        KnowledgeEdgeRead(
            id=edge.id,
            source_topic_id=edge.source_topic_id,
            target_topic_id=edge.target_topic_id,
            relationship_type=edge.relationship_type,
            supporting_chunk_count=edge.supporting_chunk_count,
            sources=_sources_for(session, edge),
        )
        for edge in edges
        if edge.source_topic_id in by_id and edge.target_topic_id in by_id
    ]
    return nodes, rendered_edges


@router.get(
    "/courses/{course_id}/knowledge-map",
    response_model=KnowledgeMapRead,
    responses=_RESPONSES,
    summary="Read the stored knowledge map",
)
def read_knowledge_map(
    service: KnowledgeMapServiceDep,
    mastery: MasteryServiceDep,
    session: SessionDep,
    user: CurrentUser,
    course_id: uuid.UUID,
) -> KnowledgeMapRead:
    """Never generates. An empty `edges` list means the map has not been built."""
    topics, edges = service.get(user.id, course_id)
    nodes, rendered = _render_map(session, mastery, user.id, course_id, topics, edges)
    return KnowledgeMapRead(
        course_id=course_id,
        nodes=nodes,
        edges=rendered,
        generated_at=min((edge.created_at for edge in edges), default=None),
    )


@router.post(
    "/courses/{course_id}/knowledge-map",
    response_model=KnowledgeMapGenerateResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_RESPONSES,
    summary="Derive the knowledge map from the course material",
)
def generate_knowledge_map(
    service: KnowledgeMapServiceDep,
    mastery: MasteryServiceDep,
    session: SessionDep,
    user: CurrentUser,
    course_id: uuid.UUID,
) -> KnowledgeMapGenerateResponse:
    result = service.generate(user.id, course_id)
    nodes, rendered = _render_map(
        session, mastery, user.id, course_id, result.topics, result.relationships
    )
    return KnowledgeMapGenerateResponse(
        course_id=course_id,
        nodes=nodes,
        edges=rendered,
        generated_at=min(
            (edge.created_at for edge in result.relationships), default=None
        ),
        candidates_rejected=result.rejected_count,
        model_calls=result.model_calls,
    )


@router.get(
    "/courses/{course_id}/knowledge-gaps",
    response_model=KnowledgeGapsRead,
    responses=_RESPONSES,
    summary="Detected knowledge gaps for this course",
)
def read_knowledge_gaps(
    service: KnowledgeMapServiceDep,
    user: CurrentUser,
    course_id: uuid.UUID,
) -> KnowledgeGapsRead:
    """Deterministic, computed from mastery and the stored graph.

    No model call happens here at all — this route works with the AI provider
    entirely unavailable, which is the point of keeping the algorithm in
    `services/learning/knowledge.py`.
    """
    _, edges = service.get(user.id, course_id)
    gaps = service.gaps(user.id, course_id)
    return KnowledgeGapsRead(
        course_id=course_id,
        gaps=[
            KnowledgeGapRead(
                topic_id=gap.topic_id,
                name=gap.name,
                kind=gap.kind,
                kind_label=GAP_KIND_LABELS[gap.kind],
                severity=gap.severity,
                effective_mastery=gap.effective_mastery,
                blocked_topics=gap.blocked_topics,
                attempted_dependents=gap.attempted_dependents,
                reason=gap.reason,
            )
            for gap in gaps
        ],
        has_map=bool(edges),
    )
