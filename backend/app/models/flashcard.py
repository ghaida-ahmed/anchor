import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.course import Course
    from app.models.document import Document
    from app.models.document_chunk import DocumentChunk
    from app.models.flashcard_review import FlashcardReviewState
    from app.models.topic import Topic
    from app.models.user import User


class Flashcard(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A generated prompt/answer pair, grounded in a source chunk.

    Persisted so opening the tab costs nothing — regenerating on every page load
    would burn free-tier quota for identical output.

    Scheduling lives in `FlashcardReviewState`, keyed by (user, card), not here:
    a card is content, and when to see it again belongs to the person reviewing it.
    """

    __tablename__ = "flashcards"
    __table_args__ = (Index("ix_flashcards_user_course", "user_id", "course_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), index=True, nullable=False
    )
    front: Mapped[str] = mapped_column(Text, nullable=False)
    back: Mapped[str] = mapped_column(Text, nullable=False)

    source_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="SET NULL"), nullable=True
    )
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )

    user: Mapped["User"] = relationship(back_populates="flashcards")
    course: Mapped["Course"] = relationship(back_populates="flashcards")
    topic: Mapped["Topic"] = relationship()
    source_chunk: Mapped["DocumentChunk | None"] = relationship()
    source_document: Mapped["Document | None"] = relationship()
    review_states: Mapped[list["FlashcardReviewState"]] = relationship(
        back_populates="flashcard",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Flashcard {self.front[:40]}…>"
