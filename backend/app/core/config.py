"""Application settings, loaded from the environment.

Every value is read here and nowhere else, so there is exactly one place to look
when adding configuration. Secrets are never defaulted to a real value.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_SECRET = "dev-only-insecure-secret-change-me"
# RFC 7518 recommends at least 32 bytes for HS256.
_MIN_SECRET_LENGTH = 32

# Which vendor backs generation and embeddings. Selected by configuration only —
# no code outside the two provider factories branches on this.
AIProvider = Literal["gemini", "openai"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application ---------------------------------------------------------
    APP_NAME: str = "ANCHOR API"
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = True
    API_PREFIX: str = "/api"

    # --- Database ------------------------------------------------------------
    # SQLAlchemy URL. Uses the psycopg 3 driver: postgresql+psycopg://...
    DATABASE_URL: str = "postgresql+psycopg://anchor:anchor@localhost:5432/anchor"

    # --- CORS ----------------------------------------------------------------
    # Origins allowed to call the API from a browser. The Vite dev server by default.
    CORS_ORIGINS: list[str] = Field(default=["http://localhost:5173"])

    # --- Authentication ------------------------------------------------------
    # Signing key for access tokens. The default below is a development
    # convenience only; startup refuses it outside development (see below).
    SECRET_KEY: str = _DEV_SECRET
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_TTL_MINUTES: int = 60 * 12

    # --- Uploads -------------------------------------------------------------
    # Filesystem root for the local storage backend. Relative paths resolve
    # against the backend package directory.
    UPLOAD_DIR: str = "storage/documents"
    MAX_UPLOAD_BYTES: int = 25 * 1024 * 1024  # 25 MB

    # --- AI providers --------------------------------------------------------
    # Gemini is the default: its free tier makes the project runnable during
    # development without a billing account. OpenAI remains fully supported and is
    # selected by configuration alone — no code in the RAG pipeline knows which is
    # active. Generation and embeddings are chosen separately so one can be moved
    # without the other.
    #
    # There is no VECTOR_DB_URL: embeddings live in the `vector` extension inside
    # the main PostgreSQL database, so DATABASE_URL covers both.
    #
    # The API starts without any key. Only the RAG endpoints refuse to run, with a
    # clear message — uploads, courses and auth are unaffected.
    AI_PROVIDER: AIProvider = "gemini"
    EMBEDDING_PROVIDER: AIProvider = "gemini"

    # --- Gemini (default) ----------------------------------------------------
    GEMINI_API_KEY: str | None = None
    # Flash-Lite: grounded Q&A over supplied context needs faithful instruction
    # following, not frontier reasoning. Chosen over larger Flash and Pro models
    # deliberately — see the README.
    GEMINI_LLM_MODEL: str = "gemini-3.5-flash-lite"
    # gemini-embedding-001 rather than the newer gemini-embedding-2, because only
    # -001 supports task_type (RETRIEVAL_DOCUMENT / RETRIEVAL_QUERY), which
    # measurably helps asymmetric question-to-passage retrieval.
    GEMINI_EMBEDDING_MODEL: str = "gemini-embedding-001"

    # --- OpenAI (optional) ---------------------------------------------------
    OPENAI_API_KEY: str | None = None
    OPENAI_LLM_MODEL: str = "gpt-4o-mini"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"

    # --- Embeddings ----------------------------------------------------------
    # EMBEDDING_DIMENSIONS is a property of the DATABASE COLUMN, not of a provider:
    # `document_chunks.embedding` is declared vector(1536) in migration
    # 924dcf437b93, and every provider must be configured to emit that width.
    #
    #   text-embedding-3-small  -> 1536 natively
    #   gemini-embedding-001    -> 3072 by default, truncated to 1536 via
    #                              output_dimensionality (Matryoshka). MTEB is
    #                              identical at 1536 and 3072 (68.17), and pgvector
    #                              cannot index beyond 2000 dimensions, so 1536 is
    #                              the better width regardless.
    #
    # Changing this value is NOT a config-only change: it needs a migration that
    # alters the vector column AND a full re-embed. Vectors from different models
    # are never comparable, whatever their width.
    EMBEDDING_DIMENSIONS: int = 1536
    # Inputs per embedding API call, where the provider supports batching.
    EMBEDDING_BATCH_SIZE: int = 64

    # --- Chunking ------------------------------------------------------------
    # Rationale in app/services/rag/chunking.py.
    CHUNK_TOKENS: int = 512
    CHUNK_OVERLAP_TOKENS: int = 64

    # --- Retrieval and answering ---------------------------------------------
    RAG_TOP_K_DEFAULT: int = 5
    RAG_TOP_K_MAX: int = 20
    # Cosine similarity below which a chunk is treated as irrelevant. If nothing
    # clears it, no LLM call is made and the student is told the material does not
    # cover the question.
    #
    # CALIBRATED AGAINST REAL EMBEDDINGS, not guessed. Measured over 20 queries
    # (10 on-topic, 10 off-topic) against a real course PDF with
    # gemini-embedding-001 at 1536 dimensions:
    #
    #     off-topic best match : 0.449 – 0.489
    #     on-topic  best match : 0.635 – 0.771
    #
    # 0.55 sits in the 0.145-wide gap, biased slightly low: wrongly refusing a fair
    # question is worse than passing a weak one, and the prompt already instructs
    # the model to decline when the excerpts do not cover it.
    #
    # Note this floor is provider-specific. Embedding models differ in how tightly
    # they pack unrelated text — a lexical baseline scores unrelated pairs near 0.0,
    # while Gemini rarely goes below 0.45. Re-measure when changing model.
    RAG_MIN_SIMILARITY: float = 0.55
    # Chunks more than this far below the best match are dropped before the context
    # is built. Retrieval returns a ranked list, not a relevance verdict: on a
    # narrow question the 4th hit can be unrelated material that merely scored
    # above the floor. Including it pollutes the context and — worse — produces a
    # citation implying that document supported the answer.
    RAG_CITATION_MARGIN: float = 0.15
    # Ceiling on the context assembled from retrieved chunks.
    RAG_MAX_CONTEXT_TOKENS: int = 4000
    MAX_QUESTION_CHARS: int = 1000

    @property
    def embedding_model(self) -> str:
        """Model name for the active embedding provider."""
        return (
            self.GEMINI_EMBEDDING_MODEL
            if self.EMBEDDING_PROVIDER == "gemini"
            else self.OPENAI_EMBEDDING_MODEL
        )

    @property
    def llm_model(self) -> str:
        """Model name for the active generation provider."""
        return (
            self.GEMINI_LLM_MODEL
            if self.AI_PROVIDER == "gemini"
            else self.OPENAI_LLM_MODEL
        )

    @model_validator(mode="after")
    def _validate_secret_key(self) -> "Settings":
        """Reject signing keys that would let anyone mint valid tokens.

        A BLANK key is the dangerous case, and the easy one to hit: `.env.example`
        ships `SECRET_KEY=` empty, so copying it to `.env` silently overrides the
        default with "". PyJWT will happily sign and verify with an empty key, so
        every session token becomes forgeable by anyone.

        In development a blank key falls back to the shared dev secret so the app
        still starts. Anywhere else it is fatal.
        """
        if not self.SECRET_KEY.strip():
            if self.ENVIRONMENT != "development":
                raise ValueError(
                    "SECRET_KEY is empty. Generate one with: "
                    'python -c "import secrets; print(secrets.token_urlsafe(48))"'
                )
            self.SECRET_KEY = _DEV_SECRET

        if self.ENVIRONMENT != "development":
            if self.SECRET_KEY == _DEV_SECRET:
                raise ValueError(
                    "SECRET_KEY must be set to a real value outside development."
                )
            if len(self.SECRET_KEY) < _MIN_SECRET_LENGTH:
                raise ValueError(
                    f"SECRET_KEY must be at least {_MIN_SECRET_LENGTH} characters."
                )

        return self


@lru_cache
def get_settings() -> Settings:
    """Cached so the environment is parsed once per process."""
    return Settings()


settings = get_settings()
