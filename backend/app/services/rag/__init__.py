"""Retrieval-augmented generation over a student's own course documents.

Layering, outermost first:

    RagService          orchestration: ask() and search()
    RetrievalService    the ownership-scoped vector query
    EmbeddingProvider   text -> vectors            (Gemini default, OpenAI optional)
    LLMProvider         messages -> answer         (Gemini default, OpenAI optional)
    DocumentProcessor   upload -> chunks, in the background
    extraction/         file -> pages of text
    chunking            pages -> overlapping, page-tagged chunks

Route handlers only ever touch `RagService` and `DocumentProcessor`.
"""

from app.services.rag.chunking import TextChunk, chunk_pages, count_tokens
from app.services.rag.embeddings import (
    EmbeddingError,
    EmbeddingProvider,
    GeminiEmbeddingProvider,
    OpenAIEmbeddingProvider,
    ProviderNotConfiguredError,
    get_embedding_provider,
    l2_normalise,
)
from app.services.rag.extraction import ExtractedPage, ExtractionError, get_extractor
from app.services.rag.generation import (
    GeminiLLMProvider,
    GenerationError,
    LLMProvider,
    OpenAIChatProvider,
    get_llm_provider,
)
from app.services.rag.processing import DocumentProcessor
from app.services.rag.rag_service import Answer, Citation, RagService
from app.services.rag.retrieval import RetrievalService, RetrievedChunk

__all__ = [
    "Answer",
    "Citation",
    "DocumentProcessor",
    "EmbeddingError",
    "EmbeddingProvider",
    "ExtractedPage",
    "ExtractionError",
    "GeminiEmbeddingProvider",
    "GeminiLLMProvider",
    "GenerationError",
    "LLMProvider",
    "OpenAIChatProvider",
    "OpenAIEmbeddingProvider",
    "ProviderNotConfiguredError",
    "RagService",
    "RetrievalService",
    "RetrievedChunk",
    "TextChunk",
    "chunk_pages",
    "count_tokens",
    "get_embedding_provider",
    "get_extractor",
    "get_llm_provider",
    "l2_normalise",
]
