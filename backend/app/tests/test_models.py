"""Schema-level guarantees that the API surface does not exercise directly."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import Course, Document, DocumentFileType, ProcessingStatus, User


def test_every_table_is_registered() -> None:
    assert set(Base.metadata.tables) == {
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


def test_deleting_a_user_cascades_in_the_database(session: Session) -> None:
    """ON DELETE CASCADE, verified against PostgreSQL rather than the ORM's own
    in-Python cascade."""
    user = User(
        name="Cascade Test",
        email=f"cascade-{uuid.uuid4().hex[:8]}@university.edu",
        hashed_password="not-a-real-hash",
    )
    course = Course(title="Networks", code="CS340", description="")
    course.documents.append(
        Document(
            filename="a.pdf",
            original_filename="a.pdf",
            file_type=DocumentFileType.PDF,
            file_size=10,
            storage_path="k/a.pdf",
        )
    )
    user.courses.append(course)
    session.add(user)
    session.flush()

    course_id = course.id
    session.execute(User.__table__.delete().where(User.id == user.id))
    session.expire_all()

    assert session.scalar(select(Course).where(Course.id == course_id)) is None
    assert session.scalars(select(Document)).all() == []


def test_documents_default_to_uploaded(session: Session) -> None:
    user = User(
        name="Default Test",
        email=f"default-{uuid.uuid4().hex[:8]}@university.edu",
        hashed_password="not-a-real-hash",
    )
    course = Course(title="Networks", code="CS340", description="")
    document = Document(
        filename="a.txt",
        original_filename="a.txt",
        file_type=DocumentFileType.TXT,
        file_size=4,
        storage_path="k/a.txt",
    )
    course.documents.append(document)
    user.courses.append(course)
    session.add(user)
    session.flush()

    assert document.processing_status is ProcessingStatus.UPLOADED
