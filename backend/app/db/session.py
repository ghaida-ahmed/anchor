"""Engine and session factory.

`create_engine` does not open a connection, so the application still starts (and
`/api/health` still answers) when PostgreSQL is not running.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    echo=settings.DEBUG and settings.ENVIRONMENT == "development",
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a session that is always closed."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """A standalone session for work outside a request.

    Background tasks run after the response is sent, by which time the request's
    session is closed — so they open their own via this. Used as a context manager
    rather than a generator dependency because there is no FastAPI to drive it.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
