"""Semantic search and the AI Tutor.

Both routes are authenticated and scoped to one course. Ownership is enforced in
the retrieval SQL itself (see `services/rag/retrieval.py`), so a course id from
another account reads as 404 and can never contribute chunks.
"""

import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUser, RagServiceDep
from app.core.rate_limit import rate_limit_ai
from app.schemas import (
    AskRequest,
    AskResponse,
    CitationRead,
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from app.services.rag.retrieval import page_number_for

router = APIRouter(prefix="/courses/{course_id}", tags=["ai-tutor"])

_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated."},
    status.HTTP_404_NOT_FOUND: {"description": "No such course for this user."},
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "description": "AI features are not configured on this server."
    },
}


@router.post(
    "/search",
    dependencies=[Depends(rate_limit_ai)],
    response_model=SearchResponse,
    responses=_RESPONSES,
    summary="Semantic search over this course's processed documents",
)
def search_course(
    service: RagServiceDep,
    user: CurrentUser,
    course_id: uuid.UUID,
    payload: SearchRequest,
) -> SearchResponse:
    """Retrieval on its own, with no generation.

    Useful for checking that semantic matching works before blaming the model, and
    the surface the retrieval evaluation exercises. Only `ready` documents take part.
    """
    chunks = service.search(user.id, course_id, payload.query, payload.top_k)

    return SearchResponse(
        query=payload.query,
        results=[
            SearchResult(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                document_name=chunk.document_name,
                # Same rule as every other citation surface: a TXT or Markdown
                # chunk has no real page, so it reports None rather than 1.
                page_number=page_number_for(chunk, chunk.file_type or ""),
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                similarity=round(chunk.similarity, 6),
                distance=round(chunk.distance, 6),
            )
            for chunk in chunks
        ],
    )


@router.post(
    "/ask",
    dependencies=[Depends(rate_limit_ai)],
    response_model=AskResponse,
    responses=_RESPONSES,
    summary="Ask a question answered from this course's materials",
)
def ask_course(
    service: RagServiceDep,
    user: CurrentUser,
    course_id: uuid.UUID,
    payload: AskRequest,
) -> AskResponse:
    """Answers strictly from retrieved course material, with citations.

    When nothing retrieved clears the relevance threshold, no model call is made and
    `is_grounded` comes back false with the standard "not enough information" reply.
    """
    result = service.ask(user.id, course_id, payload.question)

    return AskResponse(
        answer=result.answer,
        is_grounded=result.is_grounded,
        citations=[
            CitationRead(
                chunk_id=citation.chunk_id,
                document_id=citation.document_id,
                document_name=citation.document_name,
                page_number=citation.page_number,
                excerpt=citation.excerpt,
            )
            for citation in result.citations
        ],
    )
