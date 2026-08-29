"""Enable the pgvector extension.

ANCHOR stores embeddings in the same PostgreSQL database as its relational data
rather than running a separate vector service. Enabling the extension is a
migration, not a container-image detail, so any environment that runs migrations
ends up able to hold vectors.

No vector column is created here. Chunk and embedding tables arrive in Phase 3
alongside the code that populates them — an empty column now would be decoration.

Revision ID: 9c41f2b7a0e5
Revises: 7dae0b01330c
"""

from collections.abc import Sequence

from alembic import op

revision: str = "9c41f2b7a0e5"
down_revision: str | Sequence[str] | None = "7dae0b01330c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    # Safe while nothing uses a vector column; DROP EXTENSION would fail loudly
    # rather than silently once Phase 3 adds one.
    op.execute("DROP EXTENSION IF EXISTS vector")
