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

CONNECTION POOLERS
==================

Supabase (and most managed Postgres) offers a *transaction* pooler alongside the
direct connection. It is the right thing to point a web app at — it multiplexes
many short-lived application connections onto few server ones, which is exactly
what a free tier's connection cap needs.

But psycopg 3 uses server-side prepared statements by default, and a transaction
pooler hands each transaction to a different backend, so a statement prepared on
one connection is missing on the next. The result is an intermittent
`prepared statement "_pg3_0" does not exist`: it passes locally against direct
Postgres, then fails under load in production. `prepare_threshold=None` turns
prepared statements off and makes the two behave the same.

Detected from the URL rather than left to be discovered, because the failure is
intermittent and the error message does not mention pooling.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# Hostnames and ports that indicate a transaction-mode pooler.
#   6543  Supabase's Supavisor transaction port
#   6432  PgBouncer's conventional port
_POOLER_MARKERS = ("pooler.supabase.com", ":6543", ":6432", "pgbouncer=true")


def uses_transaction_pooler(url: str) -> bool:
    """Whether this URL points at a transaction-mode connection pooler."""
    lowered = url.lower()
    return any(marker in lowered for marker in _POOLER_MARKERS)


def build_engine_kwargs(url: str) -> dict:
    """Engine arguments for this database URL.

    Split out so the pooler decision is testable without opening a connection.
    """
    kwargs: dict = {
        # Checks a pooled connection is alive before handing it out. One extra
        # round-trip against a stale connection surfacing as a 500.
        "pool_pre_ping": True,
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_recycle": settings.DB_POOL_RECYCLE_SECONDS,
        # SQL echo prints statements *and their parameters*, so it is
        # development-only.
        "echo": settings.DEBUG and not settings.is_production,
    }

    if uses_transaction_pooler(url):
        # See the module docstring. Without this, prepared statements break
        # intermittently behind the pooler.
        kwargs["connect_args"] = {"prepare_threshold": None}
        # The pooler is already multiplexing; a large client-side pool just holds
        # its slots open for nothing.
        kwargs["pool_size"] = min(settings.DB_POOL_SIZE, 5)

    return kwargs


engine = create_engine(
    settings.DATABASE_URL, **build_engine_kwargs(settings.DATABASE_URL)
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
