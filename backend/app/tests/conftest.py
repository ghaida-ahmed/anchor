"""Test fixtures.

Tests run against a real PostgreSQL database, not SQLite: the application uses
PostgreSQL-specific behaviour (UUID columns, timezone-aware timestamps, ON DELETE
CASCADE) and a SQLite stand-in would verify a different system.

The schema is built by running the real Alembic migrations, so every test run also
checks that the committed migrations produce the schema the code expects.

Database selection, in order of precedence:
  1. TEST_DATABASE_URL
  2. postgresql+psycopg://anchor:anchor@localhost:5432/anchor_test  (docker compose)

Create it once with:
  docker compose exec db psql -U anchor -d postgres -c "CREATE DATABASE anchor_test"
"""

import os
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.api.deps import (
    get_embedding_factory,
    get_llm,
    get_llm_factory,
    get_session_factory,
    get_storage,
)
from app.core.config import settings
from app.db.session import get_session
from app.main import create_app
from app.services.storage import LocalStorageService
from app.tests.fakes import FakeEmbeddingProvider, FakeLLMProvider

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://anchor:anchor@localhost:5432/anchor_test",
)

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _run_migrations(url: str) -> None:
    """Apply migrations in a subprocess so Alembic reads the test URL from the env."""
    for command in (["downgrade", "base"], ["upgrade", "head"]):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *command],
            cwd=_BACKEND_ROOT,
            env={**os.environ, "DATABASE_URL": url},
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.fail(
                f"alembic {' '.join(command)} failed against the test database.\n"
                f"{result.stdout}\n{result.stderr}"
            )


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as error:  # pragma: no cover - environment problem, not a bug
        pytest.skip(f"PostgreSQL test database unavailable: {error}")

    _run_migrations(TEST_DATABASE_URL)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """A session whose writes are always rolled back.

    The outer transaction is never committed. `join_transaction_mode="create_savepoint"`
    makes the service layer's `session.commit()` release a savepoint instead, so
    production code runs unmodified while the database is left untouched.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorageService:
    """Uploads land in a per-test temp directory, never the real storage root."""
    return LocalStorageService(root=tmp_path / "documents")


@pytest.fixture(autouse=True)
def rate_limits_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable rate limiting for the suite, and reset the counters between tests.

    The limiter keys anonymous callers by IP, and every test shares TestClient's
    single address — so hundreds of requests in a few seconds would trip limits
    that a real student never would, and tests would fail by execution ORDER
    rather than by behaviour.

    `test_rate_limiting.py` re-enables it deliberately for the tests that are
    about the limiter itself. The reset still runs here so those tests cannot leak
    counters into whatever runs next.
    """
    from app.core.rate_limit import limiter

    limiter.reset()
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    yield
    limiter.reset()


@pytest.fixture(autouse=True)
def disable_automatic_topic_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep document processing free of its topic-extraction side effect.

    In production a READY document updates the course's topics automatically. Most
    tests here upload a document and then assert on an exact topic set, or on how
    many times the model was called — a background extraction consuming a scripted
    response invalidates both. Tests that want the behaviour ask for it explicitly
    with the `automatic_topic_sync` fixture.
    """
    monkeypatch.setattr(settings, "TOPIC_AUTO_SYNC", False)


@pytest.fixture
def automatic_topic_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    """Opt back in, for the tests that exist to cover it."""
    monkeypatch.setattr(settings, "TOPIC_AUTO_SYNC", True)


@pytest.fixture(autouse=True)
def fake_relevance_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the relevance floor to the fake provider's scale.

    `RAG_MIN_SIMILARITY` is calibrated for real Gemini embeddings, whose unrelated
    text rarely scores below 0.45. The lexical fake lives on a different scale
    entirely — measured over the evaluation corpus, its off-topic best matches
    reach 0.227 and its on-topic matches span 0.131-0.429. The production value
    would reject everything.

    0.30 sits just above the fake's measured off-topic ceiling. Note the ranges
    OVERLAP: a bag-of-words baseline cannot cleanly separate topical from
    off-topic text, which is exactly why retrieval quality is measured against the
    real provider (`scripts/evaluate_retrieval.py`) and not asserted here.

    Tests therefore assert *behaviour* against a threshold suited to their
    provider; that the shipped default suits the real one is asserted separately
    in test_providers.py.
    """
    monkeypatch.setattr(settings, "RAG_MIN_SIMILARITY", 0.30)


@pytest.fixture
def embeddings() -> FakeEmbeddingProvider:
    """Deterministic embeddings. No test ever calls a paid API."""
    return FakeEmbeddingProvider()


@pytest.fixture
def llm() -> FakeLLMProvider:
    return FakeLLMProvider()


@pytest.fixture
def session_factory(session: Session) -> Callable[[], AbstractContextManager[Session]]:
    """Session factory for background tasks, bound to the test transaction.

    Background processing needs its own session in production because the request's
    is closed by then. In tests it must instead reuse the transaction that gets
    rolled back — otherwise a background task would write to the real database. The
    context manager deliberately does not close the session, which the `session`
    fixture owns.
    """

    @contextmanager
    def factory() -> Iterator[Session]:
        yield session

    return factory


@pytest.fixture
def client(
    session: Session,
    storage: LocalStorageService,
    session_factory: Callable[[], AbstractContextManager[Session]],
    embeddings: FakeEmbeddingProvider,
    llm: FakeLLMProvider,
) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    # Overriding the factory covers both request-time use and background tasks.
    app.dependency_overrides[get_embedding_factory] = lambda: lambda: embeddings
    app.dependency_overrides[get_llm] = lambda: llm
    # The *factory*, for the background topic sync. Without this the processor
    # builds a real provider and reaches for the network — see get_embedding_factory
    # above for the same seam on the embedding side.
    app.dependency_overrides[get_llm_factory] = lambda: lambda: llm

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


# --- Convenience helpers -------------------------------------------------------


def register(client: TestClient, email: str, password: str = "correct-horse-9") -> str:
    """Registers an account and returns its access token."""
    response = client.post(
        "/api/v1/auth/register",
        json={"name": "Test Student", "email": email, "password": password},
    )
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def unique_email(label: str = "student") -> str:
    return f"{label}-{uuid.uuid4().hex[:10]}@university.edu"


@pytest.fixture
def token(client: TestClient) -> str:
    return register(client, unique_email())


@pytest.fixture
def other_token(client: TestClient) -> str:
    """A second, unrelated account — used for every isolation test."""
    return register(client, unique_email("other"))


@pytest.fixture
def course_id(client: TestClient, token: str) -> str:
    response = client.post(
        "/api/v1/courses",
        json={"title": "Computer Networks", "code": "CS340", "description": "Protocols."},
        headers=auth(token),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


# --- Adaptive learning helpers -------------------------------------------------


def make_topic(session: Session, course_id, name: str, description: str = ""):
    """Insert a topic directly, bypassing LLM extraction."""
    from app.models import Topic, normalise_topic_name

    topic = Topic(
        course_id=course_id,
        name=name,
        normalised_name=normalise_topic_name(name),
        description=description,
    )
    session.add(topic)
    session.flush()
    return topic


def quiz_payload(count: int = 2, *, excerpt: int = 1, difficulty: str = "medium") -> dict:
    """A well-formed generation response, for scripting the fake LLM."""
    return {
        "questions": [
            {
                "question_text": f"Grounded question {index}?",
                "options": [
                    f"Option {index}A",
                    f"Option {index}B",
                    f"Option {index}C",
                    f"Option {index}D",
                ],
                "correct_index": index % 4,
                "explanation": f"Because the excerpt says so ({index}).",
                "difficulty": difficulty,
                "excerpt_number": excerpt,
            }
            for index in range(count)
        ]
    }


# --- Phase 6 helpers ------------------------------------------------------------


def short_answer_payload(
    count: int = 1, *, excerpt: int = 1, difficulty: str = "medium"
) -> dict:
    """A well-formed short-answer generation response."""
    return {
        "questions": [
            {
                "question_text": f"Explain grounded concept {index}.",
                "reference_answer": (
                    f"The excerpt states that concept {index} works by halving the "
                    "congestion window on loss and probing upwards again."
                ),
                "key_concepts": [
                    f"halving on loss ({index})",
                    f"additive probing ({index})",
                ],
                "rubric": "A full answer names both behaviours.",
                "difficulty": difficulty,
                "excerpt_number": excerpt,
            }
            for index in range(count)
        ]
    }


def grade_payload(
    verdict: str = "correct",
    *,
    concepts: list[str] | None = None,
    satisfied: bool = True,
    feedback: str = "Both behaviours are described accurately.",
) -> dict:
    """A well-formed grading response for `short_answer_payload`'s first question."""
    names = concepts or ["halving on loss (0)", "additive probing (0)"]
    return {
        "concept_results": [{"concept": name, "satisfied": satisfied} for name in names],
        "verdict": verdict,
        "feedback": feedback,
    }


def relationship_payload(*pairs: tuple[int, str, str, list[int]]) -> dict:
    """A relationship-classification response.

    Each pair is `(pair_index, relationship, prerequisite_topic, excerpt_numbers)`.
    """
    return {
        "relationships": [
            {
                "pair_index": index,
                "relationship": relationship,
                "prerequisite_topic": side,
                "excerpt_numbers": excerpts,
            }
            for index, relationship, side, excerpts in pairs
        ]
    }


def section_payload(*, excerpt: int = 1, term: str = "Congestion window") -> dict:
    """A well-formed study-guide section response."""
    return {
        "summary": (
            "This topic covers how a sender infers congestion from loss and adjusts "
            "its sending rate. The window halves on loss and grows additively "
            "afterwards, which drains the bottleneck queue and then probes it again."
        ),
        "key_concepts": [
            "The window halves on detecting loss.",
            "Additive increase probes for capacity between losses.",
        ],
        "key_terms": [
            {
                "term": term,
                "definition": "The amount a sender may have in flight, unacknowledged.",
                "excerpt_number": excerpt,
            }
        ],
        "excerpt_numbers": [excerpt],
    }


OVERVIEW_PAYLOAD = {
    "overview": (
        "This course covers reliable transport and how senders respond to "
        "congestion. The topics build from the mechanics of acknowledgement "
        "towards the control loop that decides sending rate."
    )
}
