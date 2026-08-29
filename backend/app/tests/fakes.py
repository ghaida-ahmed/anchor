"""Deterministic stand-ins for the paid providers.

Automated tests never call OpenAI. These implement the same ABCs the production
code depends on, so the wiring under test is the real wiring — only the vendor call
is replaced.

`FakeEmbeddingProvider` produces vectors from a bag-of-words hash. That is not
semantic, but it is deterministic and it makes similar texts genuinely closer than
dissimilar ones, which is what the retrieval SQL needs to be exercised against.
Real semantic quality is checked separately, against the live API.
"""

import hashlib
import math
import re

from app.core.config import settings
from app.services.rag.embeddings import EmbeddingProvider
from app.services.rag.generation import ChatMessage, LLMProvider

_WORD = re.compile(r"[a-z0-9]+")


class FakeEmbeddingProvider(EmbeddingProvider):
    """Hashed bag-of-words vectors, L2-normalised.

    Two texts sharing vocabulary land close together under cosine distance; texts
    with no shared words are near-orthogonal. Enough to prove ranking, ownership
    filtering and thresholds behave.
    """

    def __init__(self, dimensions: int | None = None) -> None:
        self._dimensions = dimensions or settings.EMBEDDING_DIMENSIONS
        self.embed_calls: list[list[str]] = []
        self.query_calls: list[str] = []

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls.append(list(texts))
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        self.query_calls.append(text)
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self._dimensions

        for word in _WORD.findall(text.lower()):
            digest = hashlib.sha256(word.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimensions
            # Sign from a second byte so unrelated words can cancel rather than
            # only ever accumulating.
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            # An all-zero vector has undefined cosine distance; park it on one axis.
            vector[0] = 1.0
            return vector

        return [value / norm for value in vector]


class FakeLLMProvider(LLMProvider):
    """Records what it was asked and returns fixed answers.

    `json_responses` is a queue: each `generate_json` call pops the next entry, so a
    test can script a malformed reply followed by a good one and check the retry.
    When the queue is empty, `json_response` is returned repeatedly.
    """

    def __init__(self, answer: str = "A grounded answer.") -> None:
        self.answer = answer
        self.calls: list[list[ChatMessage]] = []
        self.json_calls: list[list[ChatMessage]] = []
        self.json_schemas: list[dict] = []
        self.json_response: object = {}
        self.json_responses: list[object] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    @property
    def last_user_content(self) -> str:
        if not self.calls:
            raise AssertionError("The LLM provider was never called.")
        return self.calls[-1][-1].content

    def generate(self, messages: list[ChatMessage]) -> str:
        self.calls.append(messages)
        return self.answer

    @property
    def json_call_count(self) -> int:
        return len(self.json_calls)

    @property
    def last_json_prompt(self) -> str:
        if not self.json_calls:
            raise AssertionError("generate_json was never called.")
        return self.json_calls[-1][-1].content

    def generate_json(self, messages: list[ChatMessage], schema: dict) -> object:
        self.json_calls.append(messages)
        self.json_schemas.append(schema)
        if self.json_responses:
            return self.json_responses.pop(0)
        return self.json_response


class FailingEmbeddingProvider(EmbeddingProvider):
    """Raises on use, to drive the failed-processing path."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    @property
    def dimensions(self) -> int:
        return settings.EMBEDDING_DIMENSIONS

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise self.error

    def embed_query(self, text: str) -> list[float]:
        raise self.error
