"""What a course's material currently looks like, as one comparable value.

Several artefacts are derived from a course's READY documents and must know when
that set has moved on: topics, the study guide, and the knowledge map. They all
need the same question answered — *is what I was built from still what is there?* —
so the digest lives here once rather than in each of them.

WHY A DIGEST AND NOT A TIMESTAMP

The obvious alternative is to compare `max(documents.updated_at)` against the last
extraction time. It breaks quietly: a re-extraction that finds exactly the same
topics writes no topic rows, so no timestamp moves, and the course looks
permanently out of date. A digest of the inputs has no such gap — equal inputs
produce an equal value whether or not anything was written.

Deleting a document changes it. Reprocessing one changes it, because the chunk
count is included. Answering a quiz does not, and must not: mastery is overlaid at
read time and has no business marking generated text stale.
"""

import hashlib
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk, ProcessingStatus, Topic


def material_fingerprint(session: Session, course_id: uuid.UUID) -> str:
    """A digest of the course's READY documents.

    Only READY documents count. A document still processing has no chunks to
    derive anything from, and treating it as material would make the course look
    out of date for as long as it takes to embed.
    """
    rows = session.execute(
        select(Document.id, func.count(DocumentChunk.id))
        .outerjoin(DocumentChunk, DocumentChunk.document_id == Document.id)
        .where(
            Document.course_id == course_id,
            Document.processing_status == ProcessingStatus.READY,
        )
        .group_by(Document.id)
        .order_by(Document.id)
    ).all()

    digest = hashlib.sha256()
    for document_id, chunk_count in rows:
        digest.update(f"d:{document_id}:{chunk_count}\n".encode())
    return digest.hexdigest()


def material_and_topics_fingerprint(session: Session, course_id: uuid.UUID) -> str:
    """The material digest, extended with the active topic set.

    For artefacts written *from* the topics — the study guide, whose sections are
    one per topic. Those must regenerate when the topics change, not only when the
    documents do.
    """
    topic_ids = session.scalars(
        select(Topic.id)
        .where(Topic.course_id == course_id, Topic.is_active.is_(True))
        .order_by(Topic.id)
    ).all()

    digest = hashlib.sha256()
    digest.update(material_fingerprint(session, course_id).encode())
    for topic_id in topic_ids:
        digest.update(f"t:{topic_id}\n".encode())
    return digest.hexdigest()
