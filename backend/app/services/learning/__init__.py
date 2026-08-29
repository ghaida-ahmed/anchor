"""The adaptive learning engine.

The division of labour, which is the point of this package:

    DETERMINISTIC (here)                 GENERATIVE (Gemini, via services/rag)
    ------------------------------       -----------------------------------
    which topics to practise             writing the questions
    at what difficulty                   writing the explanations
    how mastery changes                  writing flashcards
    how mastery decays with time         naming topics found in the material
    when a card is due                   judging how two topics relate
    what to recommend next               marking a written answer to a rubric
    exam readiness and priority          writing the study guide's prose
    which topics are knowledge gaps
    what a verdict does to mastery
    where the student's day begins

Everything in the left column is a pure function of the database, unit-tested and
reproducible. Nothing in it calls a model.
"""

from app.services.learning.adaptive import (
    SelectedTopic,
    TopicCandidate,
    allocate_questions,
    difficulty_plan,
    priority_for,
    select_topics,
)
from app.services.learning.analytics import AnalyticsService, CourseAnalytics
from app.services.learning.exam import ReadinessBreakdown, exam_priority, exam_readiness
from app.services.learning.exam_service import ExamService, ExamStatus
from app.services.learning.flashcard_service import FlashcardService
from app.services.learning.grading import GradeOutcome, score_attempt
from app.services.learning.grading_service import GradingResult, GradingService
from app.services.learning.grounding import InsufficientMaterialError
from app.services.learning.knowledge import KnowledgeGap, TopicNode, detect_gaps
from app.services.learning.knowledge_service import KnowledgeMapService
from app.services.learning.mastery import (
    MasteryState,
    apply_answer,
    apply_flashcard_review,
    apply_short_answer,
    band_for,
    displayed_mastery,
)
from app.services.learning.mastery_service import MasteryService
from app.services.learning.quiz_service import (
    QuizFormat,
    QuizGenerationError,
    QuizService,
)
from app.services.learning.recommendations import Recommendation
from app.services.learning.retention import effective_mastery
from app.services.learning.review_service import DueSummary, ReviewService
from app.services.learning.scheduling import ScheduleState, schedule
from app.services.learning.study_guide_service import StudyGuideService
from app.services.learning.topic_service import TopicService

__all__ = [
    "score_attempt",
    "detect_gaps",
    "apply_short_answer",
    "TopicNode",
    "StudyGuideService",
    "QuizFormat",
    "KnowledgeMapService",
    "KnowledgeGap",
    "GradingService",
    "GradingResult",
    "GradeOutcome",
    "AnalyticsService",
    "CourseAnalytics",
    "DueSummary",
    "ExamService",
    "ExamStatus",
    "FlashcardService",
    "InsufficientMaterialError",
    "MasteryService",
    "MasteryState",
    "QuizGenerationError",
    "QuizService",
    "ReadinessBreakdown",
    "Recommendation",
    "ReviewService",
    "ScheduleState",
    "SelectedTopic",
    "TopicCandidate",
    "TopicService",
    "allocate_questions",
    "apply_answer",
    "apply_flashcard_review",
    "band_for",
    "difficulty_plan",
    "displayed_mastery",
    "effective_mastery",
    "exam_priority",
    "exam_readiness",
    "priority_for",
    "schedule",
    "select_topics",
]
