"""Embedding provider abstraction, and the Gemini and OpenAI implementations.

Everything above this module works with `EmbeddingProvider`, so the pipeline has no
idea which vendor is active. Selection happens once, in `get_embedding_provider()`.

The interface separates documents from queries on purpose. Retrieval is asymmetric —
a short question is matched against a long passage — and Gemini's embedding model
takes a `task_type` that tunes for exactly that. OpenAI has no equivalent, so its
implementation embeds both the same way; the distinction stays in the interface
because the better-specified provider needs it.
"""

import math
import time
from abc import ABC, abstractmethod

from app.core.config import settings
from app.core.exceptions import AnchorError, ServiceUnavailableError

# Transient failures are retried with exponential backoff. Three attempts covers a
# brief rate limit or connection blip without stalling a background task for long.
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 1.5


class EmbeddingError(AnchorError):
    """The provider could not produce embeddings.

    Deliberately raised rather than swallowed: a document whose embeddings failed
    must end up `failed`, not silently `ready` with no chunks.
    """


class ProviderNotConfiguredError(ServiceUnavailableError):
    """No API key is set for the selected provider."""

    def __init__(self, provider: str, variable: str) -> None:
        super().__init__(
            f"AI features are not configured on this server. "
            f"Set {variable} to enable document processing and the tutor "
            f"(the active provider is '{provider}')."
        )


def l2_normalise(vector: list[float]) -> list[float]:
    """Scale a vector to unit length.

    Cosine distance assumes unit vectors. Providers that already normalise their
    output make this a no-op; those that do not would otherwise produce distances
    that are not comparable between chunks of different magnitude.
    """
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


class EmbeddingProvider(ABC):
    """Turns text into vectors of `dimensions` width."""

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Length of the vectors this provider emits. Must match the DB column."""

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed stored passages, in input order. Batched where the API allows."""

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Embed a search query."""

    def _validate(self, vectors: list[list[float]], expected: int) -> list[list[float]]:
        """Guard the one invariant the database cannot recover from."""
        if len(vectors) != expected:
            raise EmbeddingError(
                "The embedding provider returned a different number of vectors "
                "than were requested."
            )
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise EmbeddingError(
                    f"Expected {self.dimensions}-dimension embeddings but received "
                    f"{len(vector)}. Check the embedding model and "
                    f"EMBEDDING_DIMENSIONS."
                )
        return vectors


def _retry(operation, describe: str):
    """Run `operation`, retrying transient provider failures with backoff."""
    last_error: Exception | None = None

    for attempt in range(MAX_ATTEMPTS):
        try:
            return operation()
        except _TransientProviderError as error:
            last_error = error.__cause__ or error
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(BACKOFF_SECONDS * (2**attempt))

    raise EmbeddingError(
        f"The {describe} could not be reached after several attempts."
    ) from last_error


class _TransientProviderError(Exception):
    """Internal marker: worth retrying."""


# --- Gemini --------------------------------------------------------------------


class GeminiEmbeddingProvider(EmbeddingProvider):
    """`gemini-embedding-001` via the google-genai SDK.

    Two details that are easy to get wrong:

    * **Output width.** The model emits 3072 dimensions by default. We request
      `output_dimensionality=1536` (Matryoshka truncation) to match the pgvector
      column. MTEB is identical at 1536 and 3072, and pgvector cannot index past
      2000 dimensions, so this is not a compromise.
    * **Normalisation.** Only 3072-wide output is pre-normalised by the API. Any
      truncated width MUST be L2-normalised before it is compared with cosine
      distance, or ranking is silently wrong. That is done here, not left to
      callers.
    """

    def __init__(self, client=None) -> None:
        if client is None:
            if not settings.GEMINI_API_KEY:
                raise ProviderNotConfiguredError("gemini", "GEMINI_API_KEY")

            from google import genai

            client = genai.Client(api_key=settings.GEMINI_API_KEY)

        self._client = client
        self._model = settings.GEMINI_EMBEDDING_MODEL
        self._dimensions = settings.EMBEDDING_DIMENSIONS
        self._batch_size = settings.EMBEDDING_BATCH_SIZE

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            vectors.extend(self._embed(batch, task_type="RETRIEVAL_DOCUMENT"))

        return self._validate(vectors, len(texts))

    def embed_query(self, text: str) -> list[float]:
        vectors = self._embed([text], task_type="RETRIEVAL_QUERY")
        return self._validate(vectors, 1)[0]

    def _embed(self, texts: list[str], task_type: str) -> list[list[float]]:
        from google.genai import types

        config = types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=self._dimensions,
        )

        def call():
            try:
                return self._client.models.embed_content(
                    model=self._model, contents=texts, config=config
                )
            except Exception as error:
                raise _classify_gemini_error(error) from error

        response = _retry(call, "embedding provider")

        embeddings = getattr(response, "embeddings", None)
        if not embeddings:
            raise EmbeddingError("The embedding provider returned no vectors.")

        # Truncated widths are not normalised by the API — see the class docstring.
        return [l2_normalise(list(item.values)) for item in embeddings]


def _classify_gemini_error(error: Exception) -> Exception:
    """Decide whether a google-genai failure is worth retrying.

    Rate limits and transport problems are transient. A 400 or a bad API key will
    not fix itself, so it fails immediately rather than burning the backoff budget.
    """
    status = getattr(error, "code", None) or getattr(error, "status_code", None)
    message = str(error).lower()

    transient_status = status in (408, 429, 500, 502, 503, 504)
    transient_text = any(
        marker in message
        for marker in ("rate limit", "resource_exhausted", "timeout", "unavailable")
    )

    if transient_status or transient_text:
        return _TransientProviderError(str(error))

    if status in (401, 403) or "api key" in message or "permission" in message:
        return EmbeddingError("The AI provider rejected the credentials.")

    return EmbeddingError(f"The AI provider rejected the request ({status or 'error'}).")


# --- OpenAI (optional) ---------------------------------------------------------


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """`text-embedding-3-small` via the openai SDK.

    OpenAI's embedding endpoint has no task-type concept, so documents and queries
    are embedded identically. Its output is already unit-normalised.
    """

    def __init__(self, client=None) -> None:
        if client is None:
            if not settings.OPENAI_API_KEY:
                raise ProviderNotConfiguredError("openai", "OPENAI_API_KEY")

            from openai import OpenAI

            client = OpenAI(api_key=settings.OPENAI_API_KEY)

        self._client = client
        self._model = settings.OPENAI_EMBEDDING_MODEL
        self._dimensions = settings.EMBEDDING_DIMENSIONS
        self._batch_size = settings.EMBEDDING_BATCH_SIZE

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            vectors.extend(self._embed(texts[start : start + self._batch_size]))

        return self._validate(vectors, len(texts))

    def embed_query(self, text: str) -> list[float]:
        return self._validate(self._embed([text]), 1)[0]

    def _embed(self, batch: list[str]) -> list[list[float]]:
        from openai import APIConnectionError, APIStatusError, RateLimitError

        def call():
            try:
                return self._client.embeddings.create(model=self._model, input=batch)
            except (RateLimitError, APIConnectionError) as error:
                raise _TransientProviderError(str(error)) from error
            except APIStatusError as error:
                raise EmbeddingError(
                    f"The embedding provider rejected the request ({error.status_code})."
                ) from error

        response = _retry(call, "embedding provider")

        # The API returns an index per item; sort by it rather than trusting order.
        items = sorted(response.data, key=lambda item: item.index)
        return [list(item.embedding) for item in items]


# --- Selection -----------------------------------------------------------------

_EMBEDDING_PROVIDERS: dict[str, type[EmbeddingProvider]] = {
    "gemini": GeminiEmbeddingProvider,
    "openai": OpenAIEmbeddingProvider,
}


def get_embedding_provider() -> EmbeddingProvider:
    """The single place embedding-provider selection happens."""
    provider = _EMBEDDING_PROVIDERS.get(settings.EMBEDDING_PROVIDER)
    if provider is None:  # pragma: no cover - Literal keeps this unreachable
        raise EmbeddingError(
            f"Unknown embedding provider '{settings.EMBEDDING_PROVIDER}'."
        )
    return provider()
