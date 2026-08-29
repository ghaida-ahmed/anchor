"""Reset document chunks for the Gemini embedding provider.

The vector COLUMN is unchanged: `document_chunks.embedding` stays `vector(1536)`.
`gemini-embedding-001` emits 3072 dimensions by default and is truncated to 1536
via `output_dimensionality` (Matryoshka), which MTEB shows costs nothing — 68.17 at
both widths — and which keeps the column under pgvector's 2000-dimension index
ceiling. So there is no schema change here.

What does change is the CONTENT. Vectors produced by different embedding models
occupy different spaces and are not comparable, whatever their width. Leaving
OpenAI-generated vectors alongside Gemini-generated ones would not raise an error;
it would silently return nonsense rankings, which is worse. So every existing chunk
is removed and its document is set back to `uploaded` for re-processing.

This is destructive to DERIVED data only. Uploaded files are untouched, and chunks
are rebuilt from them. To regenerate after upgrading:

    POST /api/v1/documents/{document_id}/reprocess

for each affected document, or delete and re-upload. Documents left at `uploaded`
are simply not searchable until reprocessed; nothing is lost.

It also corrects `documents.processing_status`'s column default, which was written
as the lowercase enum VALUE while SQLAlchemy stores member NAMES.

Revision ID: c1f83d5a47b2
Revises: 924dcf437b93
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c1f83d5a47b2"
down_revision: str | Sequence[str] | None = "924dcf437b93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Correct a latent default from migration 7dae0b01330c: SQLAlchemy's Enum
    # stores member NAMES ("UPLOADED"), but the column default was the lowercase
    # VALUE. A row inserted without the ORM setting the column explicitly became
    # unreadable ("'uploaded' is not among the defined enum values"). The ORM
    # always set it, so nothing broke in practice — but raw SQL, restores and
    # migrations could all trip over it.
    op.execute(
        "ALTER TABLE documents ALTER COLUMN processing_status SET DEFAULT 'UPLOADED'"
    )
    op.execute(
        """
        UPDATE documents
           SET processing_status = upper(processing_status)
         WHERE processing_status <> upper(processing_status)
        """
    )

    op.execute("DELETE FROM document_chunks")
    # `failed` documents are left alone: they failed before embedding, so they have
    # nothing stale to clear and their error message is still accurate.
    op.execute(
        """
        UPDATE documents
           SET processing_status = 'UPLOADED',
               processing_error = NULL
         WHERE processing_status IN ('READY', 'PROCESSING')
        """
    )


def downgrade() -> None:
    # The default stays corrected: reverting it would only restore a bug.
    # Symmetric: going back to a different provider invalidates these vectors just
    # as thoroughly. Chunks cannot be un-deleted, so the honest inverse is to clear
    # them again and let re-processing rebuild with whatever provider is active.
    op.execute("DELETE FROM document_chunks")
    op.execute(
        """
        UPDATE documents
           SET processing_status = 'UPLOADED',
               processing_error = NULL
         WHERE processing_status IN ('READY', 'PROCESSING')
        """
    )
