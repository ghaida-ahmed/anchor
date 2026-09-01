#!/usr/bin/env python3
"""Run and verify ANCHOR's migrations against a production database.

    python3 scripts/migrate_production.py preflight   # read-only checks
    python3 scripts/migrate_production.py upgrade     # alembic upgrade head
    python3 scripts/migrate_production.py verify      # confirm the schema

WHY A SCRIPT INSTEAD OF `alembic upgrade head`
==============================================

Three reasons, all learned from the ways this goes wrong:

1. **The connection string must never reach a terminal, a log or a transcript.**
   Every line this prints passes through `redact()`, and a failure prints the
   exception *type* and a redacted message rather than a traceback — SQLAlchemy's
   connection errors quote the DSN, password included.

2. **pgvector may not be where the migration expects.** Supabase installs
   extensions into an `extensions` schema, not `public`. Migration 924dcf437b93
   declares the column as unqualified `VECTOR(1536)`, which resolves through
   `search_path`. If it does not resolve, the run fails *partway*, leaving a
   half-built schema. Preflight proves the type is reachable before anything is
   written.

3. **Only ever forward.** This script can `upgrade head` and nothing else. There
   is no downgrade path, no `stamp`, no drop, and no seed — the three commands
   above are the whole surface.

The URL is read from `backend/.env.migrate`, which `.gitignore` excludes. Use the
DIRECT connection, not the transaction pooler: Alembic runs DDL in transactions,
which needs a session-mode connection.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
ENV_FILE = BACKEND / ".env.migrate"

# Tables the migrations are expected to produce. Checked after the run so a
# partial apply is caught here rather than by a 500 in production.
EXPECTED_TABLES = {
    "alembic_version",
    "users",
    "courses",
    "documents",
    "document_chunks",
    "topics",
    "topic_mastery",
    "quizzes",
    "quiz_questions",
    "quiz_attempts",
    "quiz_answers",
    "flashcards",
    "mastery_events",
    "flashcard_review_states",
    "flashcard_reviews",
    "topic_relationships",
    "topic_relationship_evidence",
    "study_guides",
    "study_guide_sections",
    "study_guide_section_sources",
}

EMBEDDING_DIMENSIONS = 1536

_DSN = re.compile(r"\b\w+(?:\+\w+)?://[^\s'\"]+")


def redact(text: str) -> str:
    """Remove anything URL-shaped. Applied to every byte this script emits."""
    return _DSN.sub("<connection-string-redacted>", text)


def say(message: str = "") -> None:
    print(redact(message))


def fail(message: str) -> None:
    say(f"\n  FAILED: {message}")
    sys.exit(1)


def load_url() -> str:
    """Read DATABASE_URL from the gitignored env file.

    Deliberately not taken from an argument or an interactive prompt: an argument
    lands in shell history and in `ps`, and a prompt would still be echoed into a
    terminal someone may be screen-sharing.
    """
    if not ENV_FILE.exists():
        fail(
            f"{ENV_FILE.relative_to(BACKEND.parent)} does not exist.\n"
            "  Create it with a single line holding your DIRECT connection URI:\n"
            "      DATABASE_URL=<paste it here>\n"
            "  The scheme must be postgresql+psycopg (not plain postgresql).\n"
            "  The file is gitignored and must stay on your machine."
        )

    # Tolerant of how the file was actually written: `DATABASE_URL=...`, an
    # `export` prefix, surrounding quotes, or just the bare URL on its own line.
    # A credential file is typed by hand under time pressure, and rejecting a
    # valid connection string over a missing prefix helps nobody.
    url = ""
    for raw_line in ENV_FILE.read_text().splitlines():
        line = raw_line.strip().lstrip("\ufeff")
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if line.startswith("DATABASE_URL="):
            url = line.split("=", 1)[1].strip()
        elif "://" in line and "=" not in line.split("://", 1)[0]:
            # A bare connection URL.
            url = line
        url = url.strip().strip('"').strip("'")

    if not url:
        fail(f"No DATABASE_URL line found in {ENV_FILE.name}.")

    if not url.startswith("postgresql+psycopg://"):
        fail(
            "DATABASE_URL must start with postgresql+psycopg:// so SQLAlchemy "
            "selects the psycopg 3 driver. Change the scheme and try again."
        )

    lowered = url.lower()
    if "pooler.supabase.com" in lowered or ":6543" in lowered:
        fail(
            "That is the TRANSACTION POOLER URL. Alembic runs DDL in "
            "transactions and needs a session-mode connection.\n"
            "  Use the DIRECT connection (db.<project-ref>.supabase.co:5432).\n"
            "  Keep the pooler URL for the running application — Render's "
            "DATABASE_URL is correct as it is."
        )

    return url


def connect(url: str):
    try:
        from sqlalchemy import create_engine

        # NullPool: this is a one-shot script, and a lingering pool would hold a
        # connection open against a free-tier limit after the work is done.
        from sqlalchemy.pool import NullPool

        engine = create_engine(url, poolclass=NullPool)
        connection = engine.connect()
    except Exception as error:  # noqa: BLE001 - reported, never re-raised
        fail(f"could not connect ({type(error).__name__}): {redact(str(error))[:160]}")
    return connection


def preflight() -> None:
    from sqlalchemy import text

    url = load_url()
    say("PREFLIGHT — read-only. Nothing is written.\n")

    connection = connect(url)
    with connection:
        version = connection.execute(text("SHOW server_version")).scalar()
        database = connection.execute(text("SELECT current_database()")).scalar()
        say(f"  connected                : PostgreSQL {version}, database {database!r}")

        row = connection.execute(
            text(
                "SELECT extversion, n.nspname FROM pg_extension e "
                "JOIN pg_namespace n ON n.oid = e.extnamespace "
                "WHERE e.extname = 'vector'"
            )
        ).first()
        if row is None:
            fail(
                "the `vector` extension is not installed.\n"
                "  Enable it in Supabase: Database -> Extensions -> vector."
            )
        say(f"  pgvector                 : {row[0]}, in schema {row[1]!r}")

        # Read this BEFORE probing: a failed probe aborts the transaction, and
        # every later query in it fails with "current transaction is aborted",
        # burying the real diagnosis.
        search_path = connection.execute(text("SHOW search_path")).scalar()
        say(f"  search_path              : {search_path}")

        # THE CHECK THAT MATTERS. The column is declared as unqualified
        # VECTOR(1536); if the type is not on the search_path this resolves to
        # nothing and the migration fails halfway through, leaving a partial
        # schema. Rolling back keeps the connection usable either way.
        try:
            connection.execute(text("SELECT 'vector'::regtype")).scalar()
            connection.execute(text("SELECT vector_dims('[1,2,3]'::vector)")).scalar()
            resolvable = True
        except Exception:  # noqa: BLE001
            connection.rollback()
            resolvable = False

        if not resolvable:
            fail(
                "the `vector` TYPE is not resolvable on this connection.\n"
                f"  pgvector is installed in schema {row[1]!r}, which is not on\n"
                f"  the search_path above, so `VECTOR(1536)` would not resolve and\n"
                "  the migration would fail partway through.\n\n"
                "  Fix it in the Supabase SQL Editor — one statement, no code change:\n"
                f'      ALTER DATABASE {database} SET search_path TO "$user", public, {row[1]};\n\n'
                "  Then open a NEW connection (the setting applies per session) and\n"
                "  run preflight again."
            )
        say("  `vector` type resolvable : yes")
        say("  vector operations work   : yes")

        existing = {
            name
            for (name,) in connection.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                )
            )
        }
        anchor_tables = existing & EXPECTED_TABLES
        say(f"  public tables present    : {len(existing)}")
        if anchor_tables:
            say(f"  ANCHOR tables already    : {len(anchor_tables)} — this is not a fresh database")
            stamped = "alembic_version" in existing
            say(f"  alembic_version present  : {stamped}")
        else:
            say("  ANCHOR tables already    : none — fresh database, as expected")

    say("\n  Preflight passed. Next: python3 scripts/migrate_production.py upgrade")


def _alembic(url: str, *args: str) -> subprocess.CompletedProcess:
    """Run alembic with the URL supplied only through the child's environment."""
    import os

    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
    )


def upgrade() -> None:
    url = load_url()
    say("UPGRADE — applying migrations forward only.\n")

    before = _alembic(url, "current")
    say(f"  revision before : {redact(before.stdout).strip() or '(none — empty database)'}")

    result = _alembic(url, "upgrade", "head")
    output = redact(result.stdout + result.stderr)

    for line in output.splitlines():
        if "Running upgrade" in line or "Running stamp" in line:
            say(f"    {line.split('INFO')[-1].strip().lstrip('[alembic.runtime.migration] ')}")

    if result.returncode != 0:
        say("\n  --- alembic output (redacted) ---")
        for line in output.splitlines()[-15:]:
            say(f"    {line}")
        fail("alembic exited non-zero. The database may be partially migrated; "
             "run preflight again to see its state.")

    after = _alembic(url, "current")
    say(f"\n  revision after  : {redact(after.stdout).strip()}")

    check = _alembic(url, "check")
    drift = "No new upgrade operations detected" in (check.stdout + check.stderr)
    say(f"  schema matches models : {'yes' if drift else 'NO — drift detected'}")

    say("\n  Upgrade complete. Next: python3 scripts/migrate_production.py verify")


def verify() -> None:
    from sqlalchemy import text

    url = load_url()
    say("VERIFY — read-only.\n")

    connection = connect(url)
    ok = True
    with connection:
        tables = {
            name
            for (name,) in connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
        }
        missing = EXPECTED_TABLES - tables
        extra = tables - EXPECTED_TABLES
        say(f"  tables            : {len(tables & EXPECTED_TABLES)}/{len(EXPECTED_TABLES)} expected")
        if missing:
            ok = False
            say(f"  MISSING           : {sorted(missing)}")
        if extra:
            say(f"  additional        : {sorted(extra)}")

        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
        say(f"  alembic revision  : {revision}")

        # The embedding column is the one piece of schema the whole RAG pipeline
        # depends on, so its type and width are asserted rather than assumed.
        dims = connection.execute(
            text(
                "SELECT a.atttypmod FROM pg_attribute a "
                "JOIN pg_class c ON c.oid = a.attrelid "
                "WHERE c.relname = 'document_chunks' AND a.attname = 'embedding'"
            )
        ).scalar()
        type_name = connection.execute(
            text(
                "SELECT format_type(a.atttypid, NULL) FROM pg_attribute a "
                "JOIN pg_class c ON c.oid = a.attrelid "
                "WHERE c.relname = 'document_chunks' AND a.attname = 'embedding'"
            )
        ).scalar()
        say(f"  embedding column  : {type_name}({dims})")
        if type_name != "vector" or dims != EMBEDDING_DIMENSIONS:
            ok = False
            say(f"  EXPECTED          : vector({EMBEDDING_DIMENSIONS})")

        users_columns = {
            name
            for (name,) in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'users'"
                )
            )
        }
        say(f"  users columns     : {len(users_columns)} (incl. timezone: "
            f"{'timezone' in users_columns}, hashed_password: "
            f"{'hashed_password' in users_columns})")
        if "hashed_password" not in users_columns:
            ok = False

        rows = connection.execute(text("SELECT count(*) FROM users")).scalar()
        say(f"  existing users    : {rows}")

    say()
    if ok:
        say("  Schema verified. The database is ready to serve.")
    else:
        fail("the schema is not what the application expects (see above).")


COMMANDS = {"preflight": preflight, "upgrade": upgrade, "verify": verify}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        say(f"usage: {Path(sys.argv[0]).name} {{{'|'.join(COMMANDS)}}}")
        sys.exit(2)
    try:
        COMMANDS[sys.argv[1]]()
    except SystemExit:
        raise
    except Exception as error:  # noqa: BLE001
        # A traceback can quote the DSN, password included. Type and a redacted,
        # truncated message only.
        fail(f"{type(error).__name__}: {redact(str(error))[:200]}")
