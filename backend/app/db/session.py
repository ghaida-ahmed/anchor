"""Engine and session factory.

`create_engine` does not open a connection, so the application still starts (and
`/api/health` still answers) when PostgreSQL is not running. Readiness, which is a
different question, does check — see `/api/ready`.

Pool sizing is configuration rather than a constant because it is a property of the
deployment, not of the code. Managed Postgres free tiers cap total connections
low — often 20-30 shared across every client — so the defaults are smaller than
SQLAlchemy's, and `pool_recycle` sits below typical provider idle timeouts so the
first query after a quiet period does not land on a connection the server already
closed.

TLS is not configured here. Providers that require it advertise it in the URL
(`?sslmode=require`), which keeps one connection string as the single source of
truth instead of splitting it across a URL and a connect_args dict.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    # Checks a pooled connection is alive before handing it out. One extra
    # round-trip against a stale connection surfacing as a 500.
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
    # SQL echo prints statements *and their parameters*, so it is development-only.
    echo=settings.DEBUG and not settings.is_production,
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
