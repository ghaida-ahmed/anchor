from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.course import Course
    from app.models.flashcard import Flashcard
    from app.models.flashcard_review import FlashcardReviewState
    from app.models.mastery import TopicMastery
    from app.models.quiz import Quiz
    from app.models.quiz_attempt import QuizAttempt


class User(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "users"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    # bcrypt digest. The plaintext password never reaches the ORM layer.
    hashed_password: Mapped[str] = mapped_column(String(128), nullable=False)
    # IANA identifier, e.g. "Asia/Riyadh". Never a fixed offset like "UTC+3", which
    # cannot express daylight saving. Existing accounts default to UTC rather than
    # a guessed location; the student sets it explicitly.
    timezone: Mapped[str] = mapped_column(
        String(64), default="UTC", server_default="UTC", nullable=False
    )

    courses: Mapped[list["Course"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    topic_mastery: Mapped[list["TopicMastery"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    quizzes: Mapped[list["Quiz"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    quiz_attempts: Mapped[list["QuizAttempt"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    flashcards: Mapped[list["Flashcard"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    review_states: Mapped[list["FlashcardReviewState"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<User {self.email}>"
