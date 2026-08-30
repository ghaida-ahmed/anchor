"""Adaptive learning endpoints: topics, quizzes, attempts, mastery, flashcards.

Every route derives ownership from `CurrentUser`; no id from the client is trusted
without a scoped query behind it. Course, quiz, attempt, question, topic and
flashcard ids are all validated against the caller inside the service layer's
queries rather than fetched and checked afterwards.
"""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import (
    CurrentUser,
    FlashcardServiceDep,
    MasteryServiceDep,
    QuizServiceDep,
    ReviewServiceDep,
    SessionDep,
    TopicServiceDep,
)
from app.core.clock import now
from app.core.rate_limit import rate_limit_ai
from app.models import (
    Document,
    DocumentChunk,
    Flashcard,
    GradingState,
    QuestionType,
    Quiz,
    QuizAnswer,
    QuizQuestion,
    Topic,
)
from app.schemas import (
    AnswerResult,
    AnswerSubmit,
    AttemptRead,
    AttemptSummary,
    ConceptResultRead,
    CourseMasteryRead,
    FlashcardGenerateRequest,
    FlashcardRead,
    QuizDetail,
    QuizGenerateRequest,
    QuizQuestionRead,
    QuizRead,
    RecommendationRead,
    ShortAnswerSubmit,
    SourceRef,
    TopicExtractionResponse,
    TopicRead,
    TopicRetentionRead,
)
from app.services.learning import recommendations as recommender
from app.services.learning.grounding import page_number_for
from app.services.learning.mastery import BAND_LABELS, accuracy, band_for
from app.services.learning.retention import (
    RETENTION_LABELS,
    days_since_practice,
    effective_mastery,
    retention_status,
)
from app.services.rag.retrieval import RetrievedChunk

router = APIRouter(tags=["adaptive-learning"])

_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated."},
    status.HTTP_404_NOT_FOUND: {"description": "Not found for this user."},
    status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "AI provider not configured."},
}


# --- Source rendering ----------------------------------------------------------


def _source_for(
    session: Session, chunk_id: uuid.UUID | None, document_id: uuid.UUID | None
) -> SourceRef | None:
    """Build a citation from the stored rows.

    Reading the document name and page at render time means a renamed file stays
    correct, and a page number can never have been invented by the model.
    """
    if chunk_id is None or document_id is None:
        return None

    chunk = session.get(DocumentChunk, chunk_id)
    document = session.get(Document, document_id)
    if chunk is None or document is None:
        # The source was deleted after generation. Better to show no citation than
        # a dangling one.
        return None

    reference = RetrievedChunk(
        chunk_id=chunk.id,
        document_id=document.id,
        document_name=document.filename,
        page_number=chunk.page_number,
        chunk_index=chunk.chunk_index,
        content=chunk.content,
        similarity=1.0,
    )

    return SourceRef(
        document_id=document.id,
        document_name=document.filename,
        page_number=page_number_for(reference, document.file_type),
        chunk_id=chunk.id,
    )


def _short_answer_result(
    session: Session,
    question: QuizQuestion,
    answer: QuizAnswer,
    *,
    graded: GradingState,
) -> AnswerResult:
    """Render one graded written answer.

    The reference answer appears here and nowhere on the taking path — it is the
    short-answer equivalent of `correct_index`.
    """
    return AnswerResult(
        question_id=question.id,
        question_type=question.question_type,
        explanation=question.explanation,
        source=_source_for(
            session, question.source_chunk_id, question.source_document_id
        ),
        is_correct=answer.is_correct,
        response_text=answer.response_text,
        verdict=answer.verdict,
        grading_state=graded,
        rubric_results=[
            ConceptResultRead(
                concept=str(row.get("concept", "")),
                satisfied=bool(row.get("satisfied")),
            )
            for row in (answer.rubric_results or [])
            if isinstance(row, dict)
        ],
        feedback=answer.feedback,
        reference_answer=question.reference_answer,
        grading_failed=graded is GradingState.FAILED,
    )


def _result_for(
    session: Session, question: QuizQuestion, answer: QuizAnswer | None
) -> AnswerResult:
    """One row of a completed attempt, for either question type.

    An unanswered question is reported as unanswered rather than as a wrong guess:
    `selected_index` stays null and `is_correct` is False only where the student
    actually chose something.
    """
    if question.question_type is QuestionType.SHORT_ANSWER:
        if answer is None:
            return AnswerResult(
                question_id=question.id,
                question_type=question.question_type,
                explanation=question.explanation,
                source=_source_for(
                    session, question.source_chunk_id, question.source_document_id
                ),
                reference_answer=question.reference_answer,
            )
        return _short_answer_result(
            session, question, answer, graded=answer.grading_state
        )

    return AnswerResult(
        question_id=question.id,
        question_type=question.question_type,
        explanation=question.explanation,
        source=_source_for(
            session, question.source_chunk_id, question.source_document_id
        ),
        selected_index=answer.selected_index if answer else None,
        correct_index=question.correct_index,
        is_correct=bool(answer.is_correct) if answer else False,
    )


# --- Topics --------------------------------------------------------------------


@router.get(
    "/courses/{course_id}/topics",
    response_model=list[TopicRead],
    responses=_RESPONSES,
    summary="List a course's topics",
)
def list_topics(
    service: TopicServiceDep,
    user: CurrentUser,
    course_id: uuid.UUID,
    include_inactive: bool = False,
) -> list[Topic]:
    return service.list_for_course(user.id, course_id, include_inactive=include_inactive)


@router.post(
    "/courses/{course_id}/topics/extract",
    dependencies=[Depends(rate_limit_ai)],
    response_model=TopicExtractionResponse,
    responses=_RESPONSES,
    summary="Derive topics from the course's processed material",
)
def extract_topics(
    service: TopicServiceDep, user: CurrentUser, course_id: uuid.UUID
) -> TopicExtractionResponse:
    """Safe to re-run: topics are reconciled, never wiped.

    A topic the material no longer supports is deactivated rather than deleted, so
    the mastery a student built on it survives.
    """
    result = service.extract(user.id, course_id)
    return TopicExtractionResponse(
        created=[TopicRead.model_validate(t) for t in result.created],
        reactivated=[TopicRead.model_validate(t) for t in result.reactivated],
        deactivated=[TopicRead.model_validate(t) for t in result.deactivated],
        unchanged=[TopicRead.model_validate(t) for t in result.unchanged],
    )


# --- Quizzes -------------------------------------------------------------------


def _quiz_read(quiz: Quiz) -> QuizRead:
    return QuizRead(
        id=quiz.id,
        course_id=quiz.course_id,
        title=quiz.title,
        mode=quiz.mode,
        selection_rationale=quiz.selection_rationale,
        difficulty_plan=quiz.difficulty_plan or {},
        question_count=len(quiz.questions),
        created_at=quiz.created_at,
    )


def _question_read(question: QuizQuestion) -> QuizQuestionRead:
    """The taking view — correct answer and explanation are absent by construction."""
    return QuizQuestionRead(
        id=question.id,
        position=question.position,
        question_text=question.question_text,
        question_type=question.question_type,
        # Null for a short answer, where there is nothing to choose between. The
        # reference answer and rubric are absent from this shape entirely.
        options=list(question.options) if question.options else None,
        difficulty=question.difficulty,
        topic_id=question.topic_id,
        topic_name=question.topic.name if question.topic else "",
    )


@router.get(
    "/courses/{course_id}/quizzes",
    response_model=list[QuizRead],
    responses=_RESPONSES,
    summary="List generated quizzes",
)
def list_quizzes(
    service: QuizServiceDep, user: CurrentUser, course_id: uuid.UUID
) -> list[QuizRead]:
    return [_quiz_read(quiz) for quiz in service.list_for_course(user.id, course_id)]


@router.post(
    "/courses/{course_id}/quizzes",
    dependencies=[Depends(rate_limit_ai)],
    response_model=QuizDetail,
    status_code=status.HTTP_201_CREATED,
    responses={
        **_RESPONSES,
        status.HTTP_400_BAD_REQUEST: {
            "description": "Not enough course material to generate this quiz."
        },
    },
    summary="Generate a quiz grounded in the course's material",
)
def generate_quiz(
    service: QuizServiceDep,
    user: CurrentUser,
    course_id: uuid.UUID,
    payload: QuizGenerateRequest,
) -> QuizDetail:
    """Adaptive mode lets ANCHOR's mastery algorithm choose the topics; standard
    mode uses the ones the student picked. In both cases Gemini only writes the
    questions."""
    quiz = service.generate(
        user_id=user.id,
        course_id=course_id,
        mode=payload.mode,
        question_count=payload.question_count,
        topic_ids=payload.topic_ids or None,
        difficulty=payload.difficulty,
        quiz_format=payload.quiz_format,
        # Exam hardening and review pressure are both counted in local days.
        timezone=user.timezone,
    )
    return QuizDetail(
        **_quiz_read(quiz).model_dump(),
        questions=[_question_read(question) for question in quiz.questions],
    )


@router.get(
    "/quizzes/{quiz_id}",
    response_model=QuizDetail,
    responses=_RESPONSES,
    summary="Read a quiz for taking",
)
def get_quiz(
    service: QuizServiceDep, user: CurrentUser, quiz_id: uuid.UUID
) -> QuizDetail:
    quiz = service.get(user.id, quiz_id)
    return QuizDetail(
        **_quiz_read(quiz).model_dump(),
        questions=[_question_read(question) for question in quiz.questions],
    )


# --- Attempts ------------------------------------------------------------------


@router.post(
    "/quizzes/{quiz_id}/attempts",
    response_model=AttemptRead,
    status_code=status.HTTP_201_CREATED,
    responses=_RESPONSES,
    summary="Start an attempt",
)
def start_attempt(service: QuizServiceDep, user: CurrentUser, quiz_id: uuid.UUID):
    return service.start_attempt(user.id, quiz_id)


@router.post(
    "/attempts/{attempt_id}/answers",
    response_model=AnswerResult,
    responses=_RESPONSES,
    summary="Submit one answer and reveal the result",
)
def submit_answer(
    service: QuizServiceDep,
    session: SessionDep,
    user: CurrentUser,
    attempt_id: uuid.UUID,
    payload: AnswerSubmit,
) -> AnswerResult:
    """The only place a correct answer is revealed — after the student commits."""
    answer, question = service.record_answer(
        user_id=user.id,
        attempt_id=attempt_id,
        question_id=payload.question_id,
        selected_index=payload.selected_index,
        answered_in_seconds=payload.answered_in_seconds,
    )

    return AnswerResult(
        question_id=question.id,
        question_type=question.question_type,
        selected_index=answer.selected_index,
        correct_index=question.correct_index,
        is_correct=answer.is_correct,
        explanation=question.explanation,
        source=_source_for(
            session, question.source_chunk_id, question.source_document_id
        ),
    )


@router.post(
    "/attempts/{attempt_id}/short-answers",
    dependencies=[Depends(rate_limit_ai)],
    response_model=AnswerResult,
    responses=_RESPONSES,
    summary="Submit one written answer and reveal the marking",
)
def submit_short_answer(
    service: QuizServiceDep,
    session: SessionDep,
    user: CurrentUser,
    attempt_id: uuid.UUID,
    payload: ShortAnswerSubmit,
) -> AnswerResult:
    """Grade one written answer.

    A separate route from `/answers` rather than one endpoint with two optional
    fields: the two submissions carry different data and fail in different ways,
    and a single shape would make "which field is required" depend on a row the
    client cannot see.

    Grading runs inline, so this request is slower than a multiple-choice one. If
    the grader cannot be reached the answer is still recorded, `grading_state` comes
    back FAILED, and mastery is untouched — the student is never marked wrong
    because a provider was down.
    """
    answer, question, result = service.record_short_answer(
        user_id=user.id,
        attempt_id=attempt_id,
        question_id=payload.question_id,
        response_text=payload.response_text,
        answered_in_seconds=payload.answered_in_seconds,
    )
    return _short_answer_result(session, question, answer, graded=result.state)


@router.post(
    "/attempts/{attempt_id}/complete",
    response_model=AttemptSummary,
    responses=_RESPONSES,
    summary="Complete an attempt and read the full result",
)
def complete_attempt(
    service: QuizServiceDep,
    session: SessionDep,
    user: CurrentUser,
    attempt_id: uuid.UUID,
) -> AttemptSummary:
    attempt = service.complete_attempt(user.id, attempt_id)
    quiz = service.get(user.id, attempt.quiz_id)

    answered = {answer.question_id: answer for answer in attempt.answers}
    results = [
        _result_for(session, question, answered.get(question.id))
        for question in quiz.questions
    ]

    return AttemptSummary(
        id=attempt.id,
        quiz_id=attempt.quiz_id,
        started_at=attempt.started_at,
        completed_at=attempt.completed_at,
        score_percent=attempt.score_percent,
        correct_count=attempt.correct_count,
        quiz_title=quiz.title,
        question_count=len(quiz.questions),
        results=results,
    )


# --- Mastery and recommendations ------------------------------------------------


@router.get(
    "/courses/{course_id}/mastery",
    response_model=CourseMasteryRead,
    responses=_RESPONSES,
    summary="Mastery across the course, stored and effective",
)
def read_mastery(
    service: MasteryServiceDep,
    reviews: ReviewServiceDep,
    user: CurrentUser,
    course_id: uuid.UUID,
) -> CourseMasteryRead:
    """Pure database read plus arithmetic — no model call, so this costs nothing.

    Reports THREE headline numbers rather than one, because a single average is
    always misleading here:

      course_mastery     mean effective mastery over ALL active topics, counting
                         never-started ones as zero. Breadth counts.
      practised_mastery  mean over started topics only — how well the student knows
                         what they have actually studied.
      coverage           how much of the course has been touched at all.

    Reporting only the first would demoralise a student three topics into a course;
    reporting only the second would let someone claim 90% having attempted one topic
    of ten.
    """
    moment = now()
    due_counts = reviews.due_by_topic(
        user.id, course_id, at=moment, timezone=user.timezone
    )
    entries = service.for_course(user.id, course_id)

    topics: list[TopicRetentionRead] = []
    for topic, state in entries:
        effective = effective_mastery(
            state.mastery_score, state.evidence, state.last_practised_at, at=moment
        )
        elapsed = days_since_practice(state.last_practised_at, at=moment)
        due = due_counts.get(topic.id, 0)
        status_ = retention_status(
            has_evidence=state.has_evidence,
            days_since_practice=elapsed,
            due_cards=due,
        )
        band = band_for(state)

        topics.append(
            TopicRetentionRead(
                topic_id=topic.id,
                topic_name=topic.name,
                mastery_score=round(state.mastery_score, 1),
                effective_mastery=round(effective, 1),
                band=band,
                band_label=BAND_LABELS[band],
                effective_band=_effective_band(state, effective),
                retention_status=status_,
                retention_label=RETENTION_LABELS[status_],
                questions_attempted=state.questions_attempted,
                correct_answers=state.correct_answers,
                flashcard_reviews=state.flashcard_reviews,
                accuracy=None if accuracy(state) is None else round(accuracy(state), 1),
                days_since_practice=None if elapsed is None else round(elapsed, 1),
                last_practised_at=state.last_practised_at,
                due_cards=due,
            )
        )

    started = [
        item for item in topics if item.questions_attempted or item.flashcard_reviews
    ]
    answered = sum(item.questions_attempted for item in topics)
    correct = sum(item.correct_answers for item in topics)

    needs_review = min(
        (item for item in started),
        key=lambda item: item.effective_mastery,
        default=None,
    )

    return CourseMasteryRead(
        course_id=course_id,
        topics=topics,
        course_mastery=(
            round(sum(item.effective_mastery for item in topics) / len(topics), 1)
            if topics
            else 0.0
        ),
        practised_mastery=(
            round(sum(item.effective_mastery for item in started) / len(started), 1)
            if started
            else None
        ),
        coverage=round(len(started) / len(topics), 4) if topics else 0.0,
        topics_total=len(topics),
        topics_started=len(started),
        topics_strong=len([item for item in topics if item.effective_band == "strong"]),
        questions_answered=answered,
        correct_answers=correct,
        accuracy=round(100.0 * correct / answered, 1) if answered else None,
        strongest_topic=(
            max(started, key=lambda item: item.effective_mastery).topic_name
            if started
            else None
        ),
        weakest_topic=(
            min(started, key=lambda item: item.effective_mastery).topic_name
            if started
            else None
        ),
        needs_review_topic=needs_review.topic_name if needs_review else None,
    )


def _effective_band(state, effective: float) -> str:
    """Band by present estimate rather than demonstrated peak."""
    if not state.has_evidence:
        return "not_started"
    if effective < 40.0:
        return "needs_practice"
    if effective < 70.0:
        return "developing"
    return "strong"


@router.get(
    "/courses/{course_id}/recommendations",
    response_model=list[RecommendationRead],
    responses=_RESPONSES,
    summary="What to study next",
)
def read_recommendations(
    service: MasteryServiceDep,
    reviews: ReviewServiceDep,
    user: CurrentUser,
    course_id: uuid.UUID,
) -> list[RecommendationRead]:
    """Built from templates over the mastery table — never a model call."""
    moment = now()
    summary = reviews.summary(user.id, course_id, at=moment, timezone=user.timezone)
    candidates = service.candidates_for(
        user.id,
        course_id,
        at=moment,
        due_by_topic=reviews.due_by_topic(
            user.id, course_id, at=moment, timezone=user.timezone
        ),
    )
    return [
        RecommendationRead(
            kind=item.kind,
            title=item.title,
            detail=item.detail,
            topic_id=uuid.UUID(item.topic_id) if item.topic_id else None,
            topic_name=item.topic_name,
        )
        for item in recommender.build(
            candidates, due_cards=summary.due_now, overdue_cards=summary.overdue
        )
    ]


@router.get(
    "/courses/{course_id}/attempts",
    response_model=list[AttemptRead],
    responses=_RESPONSES,
    summary="Recent completed attempts",
)
def list_attempts(
    service: QuizServiceDep, user: CurrentUser, course_id: uuid.UUID
) -> list[AttemptRead]:
    return service.recent_attempts(user.id, course_id)


# --- Flashcards ----------------------------------------------------------------


def _flashcard_read(session: Session, card: Flashcard) -> FlashcardRead:
    return FlashcardRead(
        id=card.id,
        course_id=card.course_id,
        topic_id=card.topic_id,
        topic_name=card.topic.name if card.topic else "",
        front=card.front,
        back=card.back,
        source=_source_for(session, card.source_chunk_id, card.source_document_id),
        created_at=card.created_at,
    )


@router.get(
    "/courses/{course_id}/flashcards",
    response_model=list[FlashcardRead],
    responses=_RESPONSES,
    summary="List stored flashcards",
)
def list_flashcards(
    service: FlashcardServiceDep,
    session: SessionDep,
    user: CurrentUser,
    course_id: uuid.UUID,
    topic_id: uuid.UUID | None = None,
) -> list[FlashcardRead]:
    """Reads stored cards. Generation is a separate, explicit action so opening the
    tab never costs an API call."""
    return [
        _flashcard_read(session, card)
        for card in service.list_for_course(user.id, course_id, topic_id)
    ]


@router.post(
    "/courses/{course_id}/flashcards",
    dependencies=[Depends(rate_limit_ai)],
    response_model=list[FlashcardRead],
    status_code=status.HTTP_201_CREATED,
    responses={
        **_RESPONSES,
        status.HTTP_400_BAD_REQUEST: {
            "description": "Not enough course material to generate flashcards."
        },
    },
    summary="Generate grounded flashcards",
)
def generate_flashcards(
    service: FlashcardServiceDep,
    session: SessionDep,
    user: CurrentUser,
    course_id: uuid.UUID,
    payload: FlashcardGenerateRequest,
) -> list[FlashcardRead]:
    cards = service.generate(
        user_id=user.id,
        course_id=course_id,
        topic_ids=payload.topic_ids or None,
        weak_topics_only=payload.weak_topics_only,
    )
    return [_flashcard_read(session, card) for card in cards]
