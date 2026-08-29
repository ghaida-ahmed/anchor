"""Provider abstraction: selection, Gemini behaviour, and dimension compatibility.

No test here reaches the network. The google-genai and openai clients are replaced
with stubs that record what they were asked and return shaped responses, so the
provider's own logic — task types, truncation, normalisation, retries, validation —
is what is under test.
"""

import math
import types as pytypes
from dataclasses import dataclass, field

import pytest

from app.core.config import settings
from app.services.rag.embeddings import (
    EmbeddingError,
    GeminiEmbeddingProvider,
    OpenAIEmbeddingProvider,
    ProviderNotConfiguredError,
    get_embedding_provider,
    l2_normalise,
)
from app.services.rag.generation import (
    SYSTEM_PROMPT,
    ChatMessage,
    GeminiLLMProvider,
    GenerationError,
    OpenAIChatProvider,
    get_llm_provider,
)

# --- Stubs ---------------------------------------------------------------------


@dataclass
class _GeminiEmbedResponse:
    embeddings: list[object]


@dataclass
class _StubGeminiModels:
    """Records calls and returns vectors of the requested width."""

    dimensions: int = 1536
    calls: list[dict] = field(default_factory=list)
    raise_error: Exception | None = None
    # Deliberately un-normalised, as truncated Gemini output is.
    magnitude: float = 7.0
    text: str = "A grounded answer."
    generate_calls: list[dict] = field(default_factory=list)

    def embed_content(self, *, model, contents, config):
        self.calls.append(
            {
                "model": model,
                "contents": list(contents),
                "task_type": config.task_type,
                "output_dimensionality": config.output_dimensionality,
            }
        )
        if self.raise_error is not None:
            raise self.raise_error

        width = config.output_dimensionality or self.dimensions
        return _GeminiEmbedResponse(
            embeddings=[
                pytypes.SimpleNamespace(values=[self.magnitude] * width) for _ in contents
            ]
        )

    def generate_content(self, *, model, contents, config):
        self.generate_calls.append(
            {
                "model": model,
                "contents": contents,
                "system_instruction": config.system_instruction,
                "temperature": config.temperature,
            }
        )
        if self.raise_error is not None:
            raise self.raise_error
        return pytypes.SimpleNamespace(text=self.text)


class _StubGeminiClient:
    def __init__(self, models: _StubGeminiModels) -> None:
        self.models = models


@pytest.fixture
def gemini_models() -> _StubGeminiModels:
    return _StubGeminiModels()


@pytest.fixture
def gemini_client(gemini_models: _StubGeminiModels) -> _StubGeminiClient:
    return _StubGeminiClient(gemini_models)


# --- Gemini embeddings ---------------------------------------------------------


class TestGeminiEmbeddings:
    def test_documents_use_the_retrieval_document_task_type(
        self, gemini_client, gemini_models
    ) -> None:
        GeminiEmbeddingProvider(client=gemini_client).embed_documents(["a passage"])

        assert gemini_models.calls[0]["task_type"] == "RETRIEVAL_DOCUMENT"

    def test_queries_use_the_retrieval_query_task_type(
        self, gemini_client, gemini_models
    ) -> None:
        GeminiEmbeddingProvider(client=gemini_client).embed_query("a question")

        assert gemini_models.calls[0]["task_type"] == "RETRIEVAL_QUERY"

    def test_documents_and_queries_share_one_model(
        self, gemini_client, gemini_models
    ) -> None:
        """Different task types, same model — mixing models would break comparison."""
        provider = GeminiEmbeddingProvider(client=gemini_client)
        provider.embed_documents(["a passage"])
        provider.embed_query("a question")

        assert {call["model"] for call in gemini_models.calls} == {
            settings.GEMINI_EMBEDDING_MODEL
        }

    def test_output_is_truncated_to_the_column_width(
        self, gemini_client, gemini_models
    ) -> None:
        vectors = GeminiEmbeddingProvider(client=gemini_client).embed_documents(["x"])

        assert (
            gemini_models.calls[0]["output_dimensionality"]
            == settings.EMBEDDING_DIMENSIONS
        )
        assert len(vectors[0]) == settings.EMBEDDING_DIMENSIONS

    def test_truncated_output_is_l2_normalised(self, gemini_client) -> None:
        """Only 3072-wide Gemini output is pre-normalised; 1536 must be normalised
        here or cosine distance is meaningless."""
        vectors = GeminiEmbeddingProvider(client=gemini_client).embed_documents(["x"])

        norm = math.sqrt(sum(value * value for value in vectors[0]))
        assert norm == pytest.approx(1.0, abs=1e-9)

    def test_query_vectors_are_also_normalised(self, gemini_client) -> None:
        vector = GeminiEmbeddingProvider(client=gemini_client).embed_query("x")

        assert math.sqrt(sum(value * value for value in vector)) == pytest.approx(
            1.0, abs=1e-9
        )

    def test_batching_respects_the_configured_size(
        self, gemini_client, gemini_models
    ) -> None:
        texts = [f"passage {index}" for index in range(settings.EMBEDDING_BATCH_SIZE + 5)]

        vectors = GeminiEmbeddingProvider(client=gemini_client).embed_documents(texts)

        assert len(gemini_models.calls) == 2
        assert len(vectors) == len(texts)

    def test_empty_input_makes_no_call(self, gemini_client, gemini_models) -> None:
        assert GeminiEmbeddingProvider(client=gemini_client).embed_documents([]) == []
        assert gemini_models.calls == []

    def test_wrong_dimension_is_rejected(self, gemini_client, gemini_models) -> None:
        """A provider silently returning the wrong width would break every insert."""
        gemini_models.dimensions = 8

        class _NarrowModels(_StubGeminiModels):
            def embed_content(self, *, model, contents, config):
                return _GeminiEmbedResponse(
                    embeddings=[
                        pytypes.SimpleNamespace(values=[1.0] * 8) for _ in contents
                    ]
                )

        provider = GeminiEmbeddingProvider(client=_StubGeminiClient(_NarrowModels()))
        with pytest.raises(EmbeddingError) as caught:
            provider.embed_documents(["x"])

        assert "dimension" in str(caught.value)

    def test_credential_failure_is_not_retried_forever(
        self, gemini_client, gemini_models
    ) -> None:
        gemini_models.raise_error = RuntimeError("API key not valid")

        with pytest.raises(EmbeddingError) as caught:
            GeminiEmbeddingProvider(client=gemini_client).embed_documents(["x"])

        assert "credentials" in str(caught.value)
        # One attempt: a bad key will not fix itself.
        assert len(gemini_models.calls) == 1

    def test_missing_key_reports_the_right_variable(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "GEMINI_API_KEY", None)

        with pytest.raises(ProviderNotConfiguredError) as caught:
            GeminiEmbeddingProvider()

        assert "GEMINI_API_KEY" in str(caught.value)


class TestNormalisation:
    def test_scales_to_unit_length(self) -> None:
        assert l2_normalise([3.0, 4.0]) == [0.6, 0.8]

    def test_zero_vector_is_left_alone(self) -> None:
        """Dividing by a zero norm would produce NaNs the database would store."""
        assert l2_normalise([0.0, 0.0]) == [0.0, 0.0]


# --- Gemini generation ---------------------------------------------------------


class TestGeminiGeneration:
    def test_returns_the_generated_text(self, gemini_client, gemini_models) -> None:
        gemini_models.text = "Loss signals congestion."

        answer = GeminiLLMProvider(client=gemini_client).generate(
            [
                ChatMessage(role="system", content=SYSTEM_PROMPT),
                ChatMessage(role="user", content="Q"),
            ]
        )

        assert answer == "Loss signals congestion."

    def test_system_prompt_becomes_a_system_instruction(
        self, gemini_client, gemini_models
    ) -> None:
        """Gemini takes the system prompt separately rather than as a message."""
        GeminiLLMProvider(client=gemini_client).generate(
            [
                ChatMessage(role="system", content=SYSTEM_PROMPT),
                ChatMessage(role="user", content="the question"),
            ]
        )

        call = gemini_models.generate_calls[0]
        assert call["system_instruction"] == SYSTEM_PROMPT
        assert "the question" in call["contents"]
        # The grounding rules must survive the provider switch unchanged.
        assert "Do not use outside knowledge" in call["system_instruction"]

    def test_uses_the_configured_model(self, gemini_client, gemini_models) -> None:
        GeminiLLMProvider(client=gemini_client).generate(
            [ChatMessage(role="user", content="Q")]
        )

        assert gemini_models.generate_calls[0]["model"] == settings.GEMINI_LLM_MODEL

    def test_empty_response_is_an_error_not_an_empty_answer(
        self, gemini_client, gemini_models
    ) -> None:
        """A safety block returns no text; presenting that as an answer would be worse."""
        gemini_models.text = ""

        with pytest.raises(GenerationError):
            GeminiLLMProvider(client=gemini_client).generate(
                [ChatMessage(role="user", content="Q")]
            )

    def test_missing_key_reports_the_right_variable(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "GEMINI_API_KEY", None)

        with pytest.raises(ProviderNotConfiguredError) as caught:
            GeminiLLMProvider()

        assert "GEMINI_API_KEY" in str(caught.value)


# --- Selection -----------------------------------------------------------------


class TestProviderSelection:
    def test_gemini_is_the_default(self) -> None:
        assert settings.AI_PROVIDER == "gemini"
        assert settings.EMBEDDING_PROVIDER == "gemini"

    def test_embedding_provider_follows_configuration(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
        monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key")

        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "gemini")
        assert isinstance(get_embedding_provider(), GeminiEmbeddingProvider)

        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "openai")
        assert isinstance(get_embedding_provider(), OpenAIEmbeddingProvider)

    def test_llm_provider_follows_configuration(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
        monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key")

        monkeypatch.setattr(settings, "AI_PROVIDER", "gemini")
        assert isinstance(get_llm_provider(), GeminiLLMProvider)

        monkeypatch.setattr(settings, "AI_PROVIDER", "openai")
        assert isinstance(get_llm_provider(), OpenAIChatProvider)

    def test_generation_and_embeddings_are_selected_independently(
        self, monkeypatch
    ) -> None:
        """One can move to a different vendor without dragging the other along."""
        monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
        monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key")
        monkeypatch.setattr(settings, "AI_PROVIDER", "openai")
        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "gemini")

        assert isinstance(get_llm_provider(), OpenAIChatProvider)
        assert isinstance(get_embedding_provider(), GeminiEmbeddingProvider)

    def test_model_names_track_the_selected_provider(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "AI_PROVIDER", "gemini")
        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "gemini")
        assert settings.llm_model == settings.GEMINI_LLM_MODEL
        assert settings.embedding_model == settings.GEMINI_EMBEDDING_MODEL

        monkeypatch.setattr(settings, "AI_PROVIDER", "openai")
        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "openai")
        assert settings.llm_model == settings.OPENAI_LLM_MODEL
        assert settings.embedding_model == settings.OPENAI_EMBEDDING_MODEL


class TestDimensionCompatibility:
    def test_configured_dimension_matches_the_database_column(self, session) -> None:
        """The one invariant that silently corrupts everything if it drifts."""
        from sqlalchemy import text

        stored = session.execute(
            text(
                "SELECT atttypmod FROM pg_attribute "
                "WHERE attrelid = 'document_chunks'::regclass AND attname = 'embedding'"
            )
        ).scalar_one()

        assert stored == settings.EMBEDDING_DIMENSIONS

    def test_relevance_floor_is_calibrated_for_the_real_provider(self) -> None:
        """The shipped default must suit real Gemini vectors, not the test fake.

        Measured over 20 queries against a real course PDF with
        gemini-embedding-001 at 1536 dimensions: off-topic best matches fell in
        0.449-0.489, on-topic in 0.635-0.771. The floor belongs in that gap.
        A value near 0.25 — plausible for a lexical baseline — never fires.
        """
        # A fresh Settings() bypasses the autouse fixture that rescales the floor
        # for the lexical test fake, so this checks what actually ships.
        from app.core.config import Settings

        assert 0.50 <= Settings().RAG_MIN_SIMILARITY <= 0.62

    def test_citation_margin_is_a_sane_relative_window(self) -> None:
        assert 0.05 <= settings.RAG_CITATION_MARGIN <= 0.30

    def test_dimension_stays_within_pgvector_index_limits(self) -> None:
        """pgvector cannot build hnsw/ivfflat indexes beyond 2000 dimensions.
        Exceeding it would permanently foreclose indexing as the corpus grows."""
        assert settings.EMBEDDING_DIMENSIONS <= 2000
