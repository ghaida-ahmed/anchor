import uuid

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings


def _require_text(value: str, label: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{label} must not be blank.")
    return stripped


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=settings.MAX_QUESTION_CHARS)
    top_k: int = Field(
        default=settings.RAG_TOP_K_DEFAULT,
        ge=1,
        le=settings.RAG_TOP_K_MAX,
        description="Number of chunks to return.",
    )

    @field_validator("query")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _require_text(value, "Query")


class SearchResult(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    # None for formats without real pages (TXT, Markdown) — never a fabricated 1.
    page_number: int | None
    chunk_index: int
    content: str
    # Cosine similarity in [-1, 1]; higher is closer.
    similarity: float
    # 1 - similarity, provided so clients need not recompute it.
    distance: float


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=settings.MAX_QUESTION_CHARS)

    @field_validator("question")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _require_text(value, "Question")


class CitationRead(BaseModel):
    """Provenance for an answer, built from stored chunks — never model output."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    # None for formats without real pages (TXT, Markdown) — never a fabricated 1.
    page_number: int | None
    excerpt: str


class AskResponse(BaseModel):
    answer: str
    citations: list[CitationRead]
    # False when no excerpt cleared the relevance threshold, so no model was called
    # and the answer is the standard "not enough information" reply.
    is_grounded: bool
