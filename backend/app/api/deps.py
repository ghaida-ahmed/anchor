"""Shared FastAPI dependencies.

`CurrentUser` is the single source of caller identity. No endpoint accepts a
`user_id` from the client — ownership always derives from the verified token, so
changing an id in a URL can never reach another user's data.
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions import AuthenticationError
from app.core.security import decode_access_token
from app.db.session import get_session, session_scope
from app.models import User
from app.services import (
    AuthService,
    CourseService,
    DocumentService,
    StorageService,
    get_storage_service,
)
from app.services.learning import (
    AnalyticsService,
    ExamService,
    FlashcardService,
    KnowledgeMapService,
    MasteryService,
    QuizService,
    ReviewService,
    StudyGuideService,
    TopicService,
)
from app.services.rag import (
    DocumentProcessor,
    EmbeddingProvider,
    LLMProvider,
    RagService,
    get_embedding_provider,
    get_llm_provider,
)
from app.services.rag.processing import EmbeddingProviderFactory, SessionFactory

SessionDep = Annotated[Session, Depends(get_session)]

# auto_error=False so a missing header raises our AuthenticationError — and so
# returns the same JSON envelope as every other failure — rather than FastAPI's.
_bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")
BearerDep = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)]


def get_storage() -> StorageService:
    return get_storage_service()


StorageDep = Annotated[StorageService, Depends(get_storage)]


def get_auth_service(session: SessionDep) -> AuthService:
    return AuthService(session)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


def get_current_user(credentials: BearerDep, service: AuthServiceDep) -> User:
    """Resolve the bearer token to a user row, or fail with 401."""
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Not authenticated.")

    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        raise AuthenticationError("That session is invalid or has expired.")

    user = service.session.get(User, user_id)
    if user is None:
        # A valid signature for a user who has since been deleted.
        raise AuthenticationError("That session is invalid or has expired.")

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_course_service(session: SessionDep) -> CourseService:
    return CourseService(session)


def get_document_service(session: SessionDep, storage: StorageDep) -> DocumentService:
    return DocumentService(session, storage)


CourseServiceDep = Annotated[CourseService, Depends(get_course_service)]
DocumentServiceDep = Annotated[DocumentService, Depends(get_document_service)]


# --- RAG -----------------------------------------------------------------------
#
# Providers are constructed per request rather than at import time. Building an
# OpenAI client raises when no key is set, and that must fail the RAG endpoints
# only — the rest of the API works fine without one.


def get_session_factory() -> SessionFactory:
    """Session factory for work that outlives the request.

    A dependency rather than a direct import so tests can substitute a factory
    bound to the test transaction.
    """
    return session_scope


SessionFactoryDep = Annotated[SessionFactory, Depends(get_session_factory)]


def get_embedding_factory() -> EmbeddingProviderFactory:
    """The embedding provider's *constructor*, not an instance.

    Background processing must not build the provider during request handling: doing
    so raises on a server with no API key and would reject the upload instead of
    marking the document failed. Overriding this one dependency also covers
    `get_embeddings` below, so tests substitute a fake in a single place.
    """
    return get_embedding_provider


EmbeddingFactoryDep = Annotated[EmbeddingProviderFactory, Depends(get_embedding_factory)]


def get_embeddings(factory: EmbeddingFactoryDep) -> EmbeddingProvider:
    """An instance, for request-time use. Raises 503 when no key is configured,
    which is the correct answer for the RAG endpoints."""
    return factory()


def get_llm() -> LLMProvider:
    return get_llm_provider()


EmbeddingProviderDep = Annotated[EmbeddingProvider, Depends(get_embeddings)]
LLMProviderDep = Annotated[LLMProvider, Depends(get_llm)]


def get_llm_factory() -> Callable[[], LLMProvider]:
    """The generation provider's *constructor*, for the same reason
    `get_embedding_factory` exists: background processing must not build it during
    request handling, where a missing key would reject the upload instead of
    letting the document process without the topic step."""
    return get_llm_provider


LLMFactoryDep = Annotated[Callable[[], LLMProvider], Depends(get_llm_factory)]


def get_document_processor(
    session_factory: SessionFactoryDep,
    storage: StorageDep,
    embedding_factory: EmbeddingFactoryDep,
    llm_factory: LLMFactoryDep,
) -> DocumentProcessor:
    return DocumentProcessor(session_factory, storage, embedding_factory, llm_factory)


def get_rag_service(
    session: SessionDep, embeddings: EmbeddingProviderDep, llm: LLMProviderDep
) -> RagService:
    return RagService(session, embeddings, llm)


DocumentProcessorDep = Annotated[DocumentProcessor, Depends(get_document_processor)]
RagServiceDep = Annotated[RagService, Depends(get_rag_service)]


# --- Adaptive learning ---------------------------------------------------------
#
# The learning services take the same provider abstractions as the RAG layer, so
# switching vendor changes nothing here.


def get_topic_service(session: SessionDep, llm: LLMProviderDep) -> TopicService:
    return TopicService(session, llm)


def get_quiz_service(
    session: SessionDep, embeddings: EmbeddingProviderDep, llm: LLMProviderDep
) -> QuizService:
    return QuizService(session, embeddings, llm)


def get_flashcard_service(
    session: SessionDep, embeddings: EmbeddingProviderDep, llm: LLMProviderDep
) -> FlashcardService:
    return FlashcardService(session, embeddings, llm)


def get_knowledge_map_service(
    session: SessionDep, embeddings: EmbeddingProviderDep, llm: LLMProviderDep
) -> KnowledgeMapService:
    return KnowledgeMapService(session, embeddings, llm)


def get_study_guide_service(
    session: SessionDep, embeddings: EmbeddingProviderDep, llm: LLMProviderDep
) -> StudyGuideService:
    return StudyGuideService(session, embeddings, llm)


def get_mastery_service(session: SessionDep) -> MasteryService:
    """No provider dependency: mastery is computed, never generated."""
    return MasteryService(session)


TopicServiceDep = Annotated[TopicService, Depends(get_topic_service)]
QuizServiceDep = Annotated[QuizService, Depends(get_quiz_service)]
FlashcardServiceDep = Annotated[FlashcardService, Depends(get_flashcard_service)]
MasteryServiceDep = Annotated[MasteryService, Depends(get_mastery_service)]
KnowledgeMapServiceDep = Annotated[
    KnowledgeMapService, Depends(get_knowledge_map_service)
]
StudyGuideServiceDep = Annotated[StudyGuideService, Depends(get_study_guide_service)]


# --- Retention -----------------------------------------------------------------
#
# None of these take a provider dependency. Scheduling, decay, analytics and exam
# readiness are arithmetic over stored data, so they must not be able to reach a
# model even by accident.


def get_review_service(session: SessionDep) -> ReviewService:
    return ReviewService(session)


def get_analytics_service(session: SessionDep) -> AnalyticsService:
    return AnalyticsService(session)


def get_exam_service(session: SessionDep) -> ExamService:
    return ExamService(session)


ReviewServiceDep = Annotated[ReviewService, Depends(get_review_service)]
AnalyticsServiceDep = Annotated[AnalyticsService, Depends(get_analytics_service)]
ExamServiceDep = Annotated[ExamService, Depends(get_exam_service)]
