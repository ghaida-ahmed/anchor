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

# The docker-compose credentials. Fine locally, fatal in production — they are in
# the README, so anyone can read them.
_DEV_DATABASE_URL = "postgresql+psycopg://anchor:anchor@localhost:5432/anchor"

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
    DATABASE_URL: str = _DEV_DATABASE_URL
    # Connection pooling. The defaults suit a single small instance, which is what
    # a portfolio deployment is. Managed Postgres free tiers cap total connections
    # low (often 20-30 across every client), so the pool is deliberately smaller
    # than SQLAlchemy's default of 5+10.
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 5
    # Recycle below the provider's idle timeout, or the first query after a quiet
    # period fails on a connection the server already dropped.
    DB_POOL_RECYCLE_SECONDS: int = 1800

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
    # Which storage backend serves uploads.
    #   local     -> UPLOAD_DIR on the container filesystem. Correct in
    #                development, and in production ONLY with a persistent volume.
    #   supabase  -> a PRIVATE Supabase Storage bucket. Survives redeploys, and is
    #                the intended production configuration.
    STORAGE_BACKEND: Literal["local", "supabase"] = "local"

    # --- Supabase Storage ----------------------------------------------------
    # Used ONLY for private object storage. ANCHOR does not use Supabase Auth, and
    # does not use the Supabase client for database access — Postgres is reached
    # through SQLAlchemy on DATABASE_URL exactly as before.
    #
    # SUPABASE_URL is the project's base URL, https://<project-ref>.supabase.co.
    # It fronts every Supabase service on its own path prefix — Storage lives at
    # /storage/v1/. The "Data API" toggle controls PostgREST at /rest/v1/ ONLY, so
    # Storage works with the Data API disabled and ANCHOR never needs it enabled.
    SUPABASE_URL: str | None = None

    # The backend's privileged Supabase key.
    #
    # Supabase's current dashboard issues opaque secret keys (`sb_secret_...`),
    # replacing the legacy `service_role` JWT. Both are used identically — an
    # opaque bearer credential in the Authorization and apikey headers — so
    # ANCHOR accepts either and never inspects the value.
    #
    # SUPABASE_SECRET_KEY is the name to use. SUPABASE_SERVICE_ROLE_KEY is kept
    # as a deprecated fallback so an existing deployment keeps working; when both
    # are set the newer name wins.
    #
    # Either way this bypasses row-level security and can read every object in the
    # project. It is a BACKEND-ONLY secret: never a VITE_ prefix, never sent to
    # the frontend, never in a build.
    SUPABASE_SECRET_KEY: str | None = None
    SUPABASE_SERVICE_ROLE_KEY: str | None = None

    SUPABASE_STORAGE_BUCKET: str = "course-documents"

    # --- Rate limiting -------------------------------------------------------
    # Requests per window, per client, per bucket. Generous enough that ordinary
    # navigation never trips them; tight enough that a loop cannot burn an API
    # quota. See app/core/rate_limit.py.
    RATE_LIMIT_ENABLED: bool = True
    # Reads: listing courses, opening a tab, polling a document's status.
    RATE_LIMIT_READ_PER_MINUTE: int = 240
    # Writes that cost nothing but a row.
    RATE_LIMIT_WRITE_PER_MINUTE: int = 60
    # Anything that calls a model. This is the one that protects the bill.
    RATE_LIMIT_AI_PER_MINUTE: int = 10
    RATE_LIMIT_AI_PER_HOUR: int = 60
    # Credential endpoints, keyed by IP rather than by user.
    RATE_LIMIT_AUTH_PER_MINUTE: int = 10
    RATE_LIMIT_AUTH_PER_HOUR: int = 60

    # Whether a document reaching READY automatically brings the course's topics
    # up to date. On by default: it is what makes topic extraction invisible to
    # the student instead of a prerequisite they have to discover.
    #
    # Turned off in the test suite, where many cases assert on exact topic sets
    # and exact model-call counts that a background extraction would invalidate.
    # Also a genuine operator kill switch if topic extraction ever misbehaves in
    # production — uploads keep working, and "Update topics" still runs manually.
    TOPIC_AUTO_SYNC: bool = True

    # --- AI cost safeguards --------------------------------------------------
    # Wall-clock ceiling on a single provider call. Without it a hung connection
    # holds a worker until the client gives up.
    AI_REQUEST_TIMEOUT_SECONDS: float = 60.0
    # Minimum gap between regenerating an expensive artefact for one course. A
    # study guide costs one call per topic; a double-click should not buy two.
    KNOWLEDGE_MAP_REGENERATE_COOLDOWN_SECONDS: int = 60
    STUDY_GUIDE_REGENERATE_COOLDOWN_SECONDS: int = 60

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
    def supabase_key(self) -> str | None:
        """The key Storage authenticates with.

        One accessor so no caller has to know both names exist, and adding a third
        naming change later touches this line alone.
        """
        return self.SUPABASE_SECRET_KEY or self.SUPABASE_SERVICE_ROLE_KEY

    @property
    def is_production(self) -> bool:
        """True outside development. Staging is held to production's rules —
        a staging box on the public internet with a dev secret is still a
        forgeable-token box."""
        return self.ENVIRONMENT != "development"

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

    @model_validator(mode="after")
    def _validate_production_config(self) -> "Settings":
        """Refuse to start in production with a configuration that is unsafe.

        Fail fast and loudly. Every one of these is a mistake that is silent at
        startup and expensive later: a debug traceback leaking a query, a CORS
        wildcard letting any origin spend the student's API quota, a database URL
        still pointing at the credentials printed in the README.

        Error messages name the VARIABLE and the problem. They never contain the
        offending value — this text reaches logs, and a log is a place secrets
        escape from.
        """
        if not self.is_production:
            return self

        problems: list[str] = []

        if self.DEBUG:
            problems.append(
                "DEBUG must be false outside development: it turns SQL echo on and "
                "would put query text, including data, into the logs."
            )

        if self.DATABASE_URL == _DEV_DATABASE_URL:
            problems.append(
                "DATABASE_URL is still the local docker-compose default, whose "
                "credentials are published in the README. Point it at the "
                "production database."
            )

        if not self.CORS_ORIGINS:
            problems.append(
                "CORS_ORIGINS is empty. Set it to the frontend's production "
                "origin(s); the browser cannot call the API otherwise."
            )
        if "*" in self.CORS_ORIGINS:
            problems.append(
                "CORS_ORIGINS contains '*'. A wildcard cannot be combined with "
                "credentialed requests, and would let any site call this API with "
                "a logged-in student's browser."
            )
        for origin in self.CORS_ORIGINS:
            if origin.startswith("http://") and "localhost" not in origin:
                problems.append(
                    "CORS_ORIGINS contains a plaintext http:// origin that is not "
                    "localhost. Bearer tokens would travel unencrypted."
                )
                break

        if self.STORAGE_BACKEND == "supabase":
            missing = [
                name
                for name, value in (
                    ("SUPABASE_URL", self.SUPABASE_URL),
                    ("SUPABASE_SECRET_KEY", self.supabase_key),
                    ("SUPABASE_STORAGE_BUCKET", self.SUPABASE_STORAGE_BUCKET),
                )
                if not value
            ]
            if missing:
                problems.append(
                    "STORAGE_BACKEND is 'supabase' but "
                    + ", ".join(missing)
                    + " is not set. Uploads would fail on the first request."
                )
        elif self.STORAGE_BACKEND == "local":
            # Not fatal: a host with a persistent volume is a legitimate setup.
            # But it is the configuration that silently loses a student's uploads
            # on a platform with an ephemeral disk, so it is worth saying out loud.
            problems_note = (
                "STORAGE_BACKEND is 'local' in production. That is correct only if "
                "a persistent volume is mounted at UPLOAD_DIR; on an ephemeral "
                "filesystem uploaded documents are lost on every deploy."
            )
            import warnings

            warnings.warn(problems_note, RuntimeWarning, stacklevel=2)

        if problems:
            joined = "\n  - ".join(problems)
            raise ValueError(
                f"Invalid configuration for ENVIRONMENT={self.ENVIRONMENT}:\n  - {joined}"
            )

        return self


@lru_cache
def get_settings() -> Settings:
    """Cached so the environment is parsed once per process."""
    return Settings()


settings = get_settings()
