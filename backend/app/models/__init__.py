"""SQLAlchemy models.

Imported together so `Base.metadata` is complete for Alembic autogenerate and so
relationship strings resolve.
"""

from app.models.course import Course
from app.models.document import Document, DocumentFileType, ProcessingStatus
from app.models.document_chunk import DocumentChunk
from app.models.flashcard import Flashcard
from app.models.flashcard_review import (
    FlashcardReview,
    FlashcardReviewState,
    ReviewRating,
)
from app.models.knowledge import (
    RelationshipType,
    TopicRelationship,
    TopicRelationshipEvidence,
)
from app.models.mastery import TopicMastery
from app.models.mastery_event import MasteryEvent, MasteryEventSource
from app.models.quiz import (
    OPTIONS_PER_QUESTION,
    Difficulty,
    QuestionType,
    Quiz,
    QuizMode,
    QuizQuestion,
)
from app.models.quiz_attempt import AnswerVerdict, GradingState, QuizAnswer, QuizAttempt
from app.models.study_guide import (
    StudyGuide,
    StudyGuideSection,
    StudyGuideSectionSource,
    StudyGuideStatus,
)
from app.models.topic import Topic, normalise_topic_name
from app.models.user import User

__all__ = [
    "TopicRelationshipEvidence",
    "TopicRelationship",
    "StudyGuideStatus",
    "StudyGuideSectionSource",
    "StudyGuideSection",
    "StudyGuide",
    "RelationshipType",
    "QuestionType",
    "GradingState",
    "AnswerVerdict",
    "OPTIONS_PER_QUESTION",
    "Course",
    "Difficulty",
    "Document",
    "DocumentChunk",
    "DocumentFileType",
    "Flashcard",
    "FlashcardReview",
    "FlashcardReviewState",
    "MasteryEvent",
    "MasteryEventSource",
    "ReviewRating",
    "ProcessingStatus",
    "Quiz",
    "QuizAnswer",
    "QuizAttempt",
    "QuizMode",
    "QuizQuestion",
    "Topic",
    "TopicMastery",
    "User",
    "normalise_topic_name",
]
