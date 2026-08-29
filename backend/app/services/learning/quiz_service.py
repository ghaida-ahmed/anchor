"""Quiz generation and the attempt lifecycle.

Generation is a four-stage pipeline, and the model only participates in stage three:

    1. decide topics + difficulty   (deterministic — adaptive.py, or the student)
    2. retrieve grounding chunks    (existing ownership-scoped vector search)
    3. generate questions           (LLM, given ONLY those chunks)
    4. validate and persist         (reject anything unsupported)

Nothing is written until every question passes stage four. A partially valid quiz is
never saved.

A quiz holds multiple-choice questions, short-answer questions, or both. The two
share stages 1, 2 and 4 and differ only in the prompt and the validation rules, so
retrieval happens once per topic no matter which formats were asked for. Multiple
choice remains the default: it is free to mark, and a quiz that says nothing about
format is the quiz Phase 4 built.
"""

import enum
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.clock import now
from app.core.config import settings
from app.core.exceptions import AnchorError, ResourceNotFoundError
from app.models import (
    OPTIONS_PER_QUESTION,
    AnswerVerdict,
    Course,
    Difficulty,
    GradingState,
    QuestionType,
    Quiz,
    QuizAnswer,
    QuizAttempt,
    QuizMode,
    QuizQuestion,
    Topic,
)
from app.services.learning.adaptive import difficulty_plan, select_topics
from app.services.learning.exam import harden_band
from app.services.learning.exam_service import ExamService
from app.services.learning.grading import score_attempt
from app.services.learning.grading_service import GradingResult, GradingService
from app.services.learning.grounding import (
    GroundingContext,
    InsufficientMaterialError,
    build_grounding_context,
)
from app.services.learning.mastery_service import MasteryService
from app.services.learning.prompts import (
    MAX_KEY_CONCEPTS,
    MIN_KEY_CONCEPTS,
    QUIZ_SCHEMA,
    QUIZ_SYSTEM,
    SHORT_ANSWER_SCHEMA,
    SHORT_ANSWER_SYSTEM,
    quiz_prompt,
    short_answer_prompt,
)
from app.services.learning.review_service import ReviewService
from app.services.rag.embeddings import EmbeddingProvider
from app.services.rag.generation import ChatMessage, GenerationError, LLMProvider
from app.services.rag.retrieval import RetrievalService

MIN_QUESTIONS = 3
MAX_QUESTIONS = 20
DEFAULT_QUESTIONS = 8

# Chunks retrieved per topic. Enough for variety without blowing the context budget.
CHUNKS_PER_TOPIC = 6

# A topic with fewer supporting chunks than this cannot carry questions honestly.
MIN_CHUNKS_PER_TOPIC = 1

# One retry on malformed output; beyond that the model is not going to comply and
# retrying only spends quota.
GENERATION_ATTEMPTS = 2

# In a mixed quiz, roughly one question in three is a short answer. Short answers
# are the better evidence but they cost a model call each to mark, so a mixed quiz
# leans on multiple choice for volume and uses short answers for depth.
SHORT_ANSWER_SHARE = 1 / 3

MIN_REFERENCE_ANSWER_CHARS = 20
MAX_REFERENCE_ANSWER_CHARS = 1_200
MIN_CONCEPT_CHARS = 3
MAX_CONCEPT_CHARS = 120


class QuizFormat(str, enum.Enum):
    """What kinds of question a generated quiz should contain.

    Separate from `QuestionType`, which describes one stored question. MCQ is the
    default so existing callers keep the Phase 4 behaviour exactly.
    """

    MCQ = "mcq"
    SHORT_ANSWER = "short_answer"
    MIXED = "mixed"


class QuizGenerationError(AnchorError):
    """Generation produced nothing usable."""


@dataclass(frozen=True)
class ValidatedQuestion:
    """One question that passed stage four, in either format.

    The multiple-choice fields and the short-answer fields are each null for the
    other type — mirroring the columns, which were relaxed to nullable for exactly
    this reason.
    """

    question_text: str
    explanation: str
    difficulty: Difficulty
    topic_id: uuid.UUID
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    question_type: QuestionType = QuestionType.MCQ
    options: list[str] | None = None
    correct_index: int | None = None
    reference_answer: str | None = None
    key_concepts: list[str] | None = None
    rubric: str | None = None


class QuizService:
    def __init__(
        self,
        session: Session,
        embeddings: EmbeddingProvider,
        llm: LLMProvider,
    ) -> None:
        self.session = session
        self.embeddings = embeddings
        self.llm = llm
        self.retrieval = RetrievalService(session)
        self.mastery = MasteryService(session)
        self.reviews = ReviewService(session)
        self.exam = ExamService(session)
        self.grader = GradingService(llm)

    # --- Generation ------------------------------------------------------------

    def generate(
        self,
        *,
        user_id: uuid.UUID,
        course_id: uuid.UUID,
        mode: QuizMode,
        question_count: int = DEFAULT_QUESTIONS,
        topic_ids: list[uuid.UUID] | None = None,
        difficulty: Difficulty | None = None,
        quiz_format: QuizFormat = QuizFormat.MCQ,
        timezone: str | None = None,
    ) -> Quiz:
        course = self._assert_course_owned(user_id, course_id)
        count = max(MIN_QUESTIONS, min(question_count, MAX_QUESTIONS))

        if mode is QuizMode.EXAM:
            plan, rationale = self._exam_plan(user_id, course_id, count, timezone)
        elif mode is QuizMode.ADAPTIVE:
            plan, rationale = self._adaptive_plan(user_id, course_id, count, timezone)
        else:
            plan, rationale = self._standard_plan(
                user_id, course_id, count, topic_ids, difficulty
            )

        if not plan:
            raise InsufficientMaterialError(
                "This course has no topics yet. Extract topics before generating a quiz."
            )

        questions: list[ValidatedQuestion] = []
        for topic, mcq_counts, short_counts in _split_by_format(plan, quiz_format):
            questions.extend(
                self._generate_for_topic(
                    user_id, course_id, topic, mcq_counts, short_counts
                )
            )

        if not questions:
            raise InsufficientMaterialError(
                "Not enough information in your course materials to generate this quiz. "
                "Try uploading more material, or choosing a different topic."
            )

        return self._persist(course, user_id, mode, rationale, questions)

    def _exam_plan(
        self,
        user_id: uuid.UUID,
        course_id: uuid.UUID,
        count: int,
        timezone: str | None = None,
    ) -> tuple[list[tuple[Topic, dict[Difficulty, int]]], str]:
        """Exam-mode plan: coverage first, hardened as the date approaches.

        The timezone reaches here because "days until the exam" decides how hard
        the questions get; measuring it in UTC would harden a day early or a day
        late depending on which side of the world the student is on.
        """
        selected, days_remaining = self.exam.select_topics(
            user_id, course_id, question_count=count, timezone=timezone
        )
        if not selected:
            return [], ""

        topics = self._topics_by_id([item.topic_id for item in selected])
        plan = [
            (
                topics[item.topic_id],
                difficulty_plan(
                    harden_band(item.band, days_remaining), item.question_count
                ),
            )
            for item in selected
            if item.topic_id in topics
        ]
        return plan, _exam_rationale(selected, days_remaining)

    def _adaptive_plan(
        self,
        user_id: uuid.UUID,
        course_id: uuid.UUID,
        count: int,
        timezone: str | None = None,
    ) -> tuple[list[tuple[Topic, dict[Difficulty, int]]], str]:
        """Topics and difficulties chosen by the deterministic engine.

        Effective mastery and review pressure are resolved here, so the selector
        stays a pure function of what it is handed.
        """
        moment = now()
        candidates = self.mastery.candidates_for(
            user_id,
            course_id,
            at=moment,
            due_by_topic=self.reviews.due_by_topic(
                user_id, course_id, at=moment, timezone=timezone
            ),
        )
        selected = select_topics(candidates, question_count=count)
        if not selected:
            return [], ""

        by_id = self._topics_by_id([item.topic_id for item in selected])
        plan = [
            (by_id[item.topic_id], difficulty_plan(item.band, item.question_count))
            for item in selected
            if item.topic_id in by_id
        ]
        return plan, _rationale_for(selected)

    def _topics_by_id(self, topic_ids: list[uuid.UUID]) -> dict[uuid.UUID, Topic]:
        return {
            topic.id: topic
            for topic in self.session.scalars(
                select(Topic).where(Topic.id.in_(topic_ids))
            )
        }

    def _standard_plan(
        self,
        user_id: uuid.UUID,
        course_id: uuid.UUID,
        count: int,
        topic_ids: list[uuid.UUID] | None,
        difficulty: Difficulty | None,
    ) -> tuple[list[tuple[Topic, dict[Difficulty, int]]], str]:
        """Topics the student picked. Ownership is scoped in the query itself."""
        query = (
            select(Topic)
            .join(Course, Course.id == Topic.course_id)
            .where(
                Topic.course_id == course_id,
                Topic.is_active.is_(True),
                Course.user_id == user_id,
            )
            .order_by(Topic.name)
        )
        if topic_ids:
            query = query.where(Topic.id.in_(topic_ids))

        topics = list(self.session.scalars(query))
        if not topics:
            return [], ""

        base, extra = divmod(count, len(topics))
        plan: list[tuple[Topic, dict[Difficulty, int]]] = []
        for index, topic in enumerate(topics):
            share = base + (1 if index < extra else 0)
            if share <= 0:
                continue
            if difficulty is not None:
                plan.append((topic, {difficulty: share}))
            else:
                # No difficulty requested: mix by what the student has shown.
                candidates = {
                    c.topic_id: c for c in self.mastery.candidates_for(user_id, course_id)
                }
                band = (
                    candidates[topic.id].band if topic.id in candidates else "not_started"
                )
                plan.append((topic, difficulty_plan(band, share)))

        names = ", ".join(topic.name for topic, _ in plan)
        return plan, f"You selected {names}."

    def _generate_for_topic(
        self,
        user_id: uuid.UUID,
        course_id: uuid.UUID,
        topic: Topic,
        mcq_counts: dict[Difficulty, int],
        short_counts: dict[Difficulty, int],
    ) -> list[ValidatedQuestion]:
        """Generate this topic's share of the quiz, in one or both formats.

        Retrieval happens once and both prompts are grounded in the same excerpts,
        so asking for a mixed quiz costs one extra generation call, not a second
        round of embedding and searching.
        """
        if sum(mcq_counts.values()) <= 0 and sum(short_counts.values()) <= 0:
            return []

        context = self._retrieve_for_topic(user_id, course_id, topic)
        if context is None:
            # No supporting material for this topic — skip it rather than let the
            # model invent questions. Other topics may still succeed.
            return []

        questions: list[ValidatedQuestion] = []

        if sum(mcq_counts.values()) > 0:
            questions.extend(
                self._ask(
                    topic,
                    context,
                    counts=mcq_counts,
                    system=QUIZ_SYSTEM,
                    prompt=quiz_prompt,
                    schema=QUIZ_SCHEMA,
                    validate=self._validate,
                )
            )

        if sum(short_counts.values()) > 0:
            questions.extend(
                self._ask(
                    topic,
                    context,
                    counts=short_counts,
                    system=SHORT_ANSWER_SYSTEM,
                    prompt=short_answer_prompt,
                    schema=SHORT_ANSWER_SCHEMA,
                    validate=self._validate_short_answer,
                )
            )

        return questions

    def _ask(
        self,
        topic: Topic,
        context: GroundingContext,
        *,
        counts: dict[Difficulty, int],
        system: str,
        prompt,
        schema: dict,
        validate,
    ) -> list[ValidatedQuestion]:
        """One generation call plus its retry, for either question format."""
        wanted = sum(counts.values())
        plan_text = ", ".join(
            f"{count} {level.value}" for level, count in counts.items() if count
        )

        messages = [
            ChatMessage(role="system", content=system),
            ChatMessage(
                role="user",
                content=prompt(topic.name, topic.description, plan_text, context.text),
            ),
        ]

        for attempt in range(GENERATION_ATTEMPTS):
            try:
                raw = self.llm.generate_json(messages, schema)
            except GenerationError:
                if attempt == GENERATION_ATTEMPTS - 1:
                    raise
                continue

            validated = validate(raw, topic, context)
            if validated:
                return validated[:wanted]

        return []

    def _validate_short_answer(
        self, raw: object, topic: Topic, context: GroundingContext
    ) -> list[ValidatedQuestion]:
        """Stage four for short answers.

        The key concepts are the load-bearing part: they become the rubric the
        grader marks against, and they are stored with the question so a later
        regrade uses the same criteria. A question without usable concepts is
        discarded — marking against an empty rubric is not marking.
        """
        if not isinstance(raw, dict):
            return []
        items = raw.get("questions")
        if not isinstance(items, list):
            return []

        validated: list[ValidatedQuestion] = []
        seen_text: set[str] = set()

        for item in items:
            if not isinstance(item, dict):
                continue

            text = str(item.get("question_text") or "").strip()
            reference = str(item.get("reference_answer") or "").strip()
            rubric = str(item.get("rubric") or "").strip()
            difficulty_raw = str(item.get("difficulty") or "").strip().lower()
            excerpt_number = item.get("excerpt_number")

            if not text or text.lower() in seen_text:
                continue
            if not (
                MIN_REFERENCE_ANSWER_CHARS <= len(reference) <= MAX_REFERENCE_ANSWER_CHARS
            ):
                continue
            if difficulty_raw not in {level.value for level in Difficulty}:
                continue
            if not isinstance(excerpt_number, int):
                continue

            concepts = _clean_concepts(item.get("key_concepts"))
            if not (MIN_KEY_CONCEPTS <= len(concepts) <= MAX_KEY_CONCEPTS):
                continue

            chunk = context.resolve(excerpt_number)
            if chunk is None:
                # Cited an excerpt we did not supply; provenance would be invented.
                continue

            seen_text.add(text.lower())
            validated.append(
                ValidatedQuestion(
                    question_text=text,
                    # The reference answer is the explanation for this format: it is
                    # what the student is shown once they have answered.
                    explanation=reference,
                    difficulty=Difficulty(difficulty_raw),
                    topic_id=topic.id,
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    question_type=QuestionType.SHORT_ANSWER,
                    reference_answer=reference,
                    key_concepts=concepts,
                    rubric=rubric,
                )
            )

        return validated

    def _retrieve_for_topic(
        self, user_id: uuid.UUID, course_id: uuid.UUID, topic: Topic
    ) -> GroundingContext | None:
        """Ownership- and course-scoped retrieval, reusing the Phase 3 vector search."""
        query = f"{topic.name}. {topic.description}".strip()
        embedding = self.embeddings.embed_query(query)

        chunks = self.retrieval.search(
            user_id,
            course_id,
            embedding,
            top_k=CHUNKS_PER_TOPIC,
            min_similarity=settings.RAG_MIN_SIMILARITY,
        )
        if len(chunks) < MIN_CHUNKS_PER_TOPIC:
            return None

        return build_grounding_context(chunks)

    def _validate(
        self, raw: object, topic: Topic, context: GroundingContext
    ) -> list[ValidatedQuestion]:
        """Reject anything a schema cannot catch.

        A JSON schema constrains shape, not truth. These checks enforce the parts
        that actually matter: four options, exactly one answer, a real explanation,
        and provenance pointing at a chunk WE supplied for THIS course.
        """
        if not isinstance(raw, dict):
            return []
        items = raw.get("questions")
        if not isinstance(items, list):
            return []

        validated: list[ValidatedQuestion] = []
        seen_text: set[str] = set()

        for item in items:
            if not isinstance(item, dict):
                continue

            text = str(item.get("question_text") or "").strip()
            options = item.get("options")
            explanation = str(item.get("explanation") or "").strip()
            difficulty_raw = str(item.get("difficulty") or "").strip().lower()
            correct_index = item.get("correct_index")
            excerpt_number = item.get("excerpt_number")

            if not text or text.lower() in seen_text:
                continue
            if not isinstance(options, list) or len(options) != OPTIONS_PER_QUESTION:
                continue
            cleaned = [str(option).strip() for option in options]
            if any(not option for option in cleaned):
                continue
            # Duplicate options make "exactly one correct answer" meaningless.
            if len({option.lower() for option in cleaned}) != OPTIONS_PER_QUESTION:
                continue
            if not isinstance(correct_index, int) or not (
                0 <= correct_index < OPTIONS_PER_QUESTION
            ):
                continue
            if not explanation:
                continue
            if difficulty_raw not in {level.value for level in Difficulty}:
                continue
            if not isinstance(excerpt_number, int):
                continue

            chunk = context.resolve(excerpt_number)
            if chunk is None:
                # The model cited an excerpt we did not supply. Provenance would be
                # fabricated, so the question is discarded.
                continue

            seen_text.add(text.lower())
            validated.append(
                ValidatedQuestion(
                    question_text=text,
                    question_type=QuestionType.MCQ,
                    options=cleaned,
                    correct_index=correct_index,
                    explanation=explanation,
                    difficulty=Difficulty(difficulty_raw),
                    topic_id=topic.id,
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                )
            )

        return validated

    def _persist(
        self,
        course: Course,
        user_id: uuid.UUID,
        mode: QuizMode,
        rationale: str,
        questions: list[ValidatedQuestion],
    ) -> Quiz:
        counts: dict[str, int] = {}
        for question in questions:
            counts[question.difficulty.value] = (
                counts.get(question.difficulty.value, 0) + 1
            )

        label = {
            QuizMode.ADAPTIVE: "Adaptive practice",
            QuizMode.EXAM: "Exam preparation",
        }.get(mode, "Practice quiz")
        quiz = Quiz(
            course_id=course.id,
            user_id=user_id,
            title=f"{label} — {course.code or course.title}",
            mode=mode,
            selection_rationale=rationale,
            difficulty_plan=counts,
        )
        self.session.add(quiz)
        self.session.flush()

        for position, question in enumerate(questions):
            self.session.add(
                QuizQuestion(
                    quiz_id=quiz.id,
                    topic_id=question.topic_id,
                    position=position,
                    question_text=question.question_text,
                    question_type=question.question_type,
                    options=question.options,
                    correct_index=question.correct_index,
                    explanation=question.explanation,
                    difficulty=question.difficulty,
                    reference_answer=question.reference_answer,
                    key_concepts=question.key_concepts,
                    rubric=question.rubric,
                    source_chunk_id=question.chunk_id,
                    source_document_id=question.document_id,
                )
            )

        self.session.commit()
        self.session.refresh(quiz)
        return quiz

    # --- Reading ---------------------------------------------------------------

    def list_for_course(self, user_id: uuid.UUID, course_id: uuid.UUID) -> list[Quiz]:
        self._assert_course_owned(user_id, course_id)
        return list(
            self.session.scalars(
                select(Quiz)
                .where(Quiz.course_id == course_id, Quiz.user_id == user_id)
                .order_by(Quiz.created_at.desc())
            )
        )

    def get(self, user_id: uuid.UUID, quiz_id: uuid.UUID) -> Quiz:
        """Ownership is a predicate in the query, not a check after loading."""
        quiz = self.session.scalar(
            select(Quiz)
            .options(selectinload(Quiz.questions))
            .where(Quiz.id == quiz_id, Quiz.user_id == user_id)
        )
        if quiz is None:
            raise ResourceNotFoundError("Quiz", str(quiz_id))
        return quiz

    # --- Attempts --------------------------------------------------------------

    def start_attempt(self, user_id: uuid.UUID, quiz_id: uuid.UUID) -> QuizAttempt:
        quiz = self.get(user_id, quiz_id)
        attempt = QuizAttempt(
            quiz_id=quiz.id, user_id=user_id, started_at=datetime.now(UTC)
        )
        self.session.add(attempt)
        self.session.commit()
        self.session.refresh(attempt)
        return attempt

    def get_attempt(self, user_id: uuid.UUID, attempt_id: uuid.UUID) -> QuizAttempt:
        attempt = self.session.scalar(
            select(QuizAttempt).where(
                QuizAttempt.id == attempt_id, QuizAttempt.user_id == user_id
            )
        )
        if attempt is None:
            raise ResourceNotFoundError("Attempt", str(attempt_id))
        return attempt

    def record_answer(
        self,
        *,
        user_id: uuid.UUID,
        attempt_id: uuid.UUID,
        question_id: uuid.UUID,
        selected_index: int,
        answered_in_seconds: int | None = None,
    ) -> tuple[QuizAnswer, QuizQuestion]:
        """Score one answer and fold it into mastery.

        Mastery updates per answer rather than at completion, so an abandoned
        attempt still counts the questions the student actually did.
        """
        attempt = self.get_attempt(user_id, attempt_id)
        if attempt.is_complete:
            raise AnchorError("This attempt has already been submitted.")

        # The question must belong to this attempt's quiz — a question id from
        # another quiz (or another user's) must not be answerable here.
        question = self.session.scalar(
            select(QuizQuestion).where(
                QuizQuestion.id == question_id, QuizQuestion.quiz_id == attempt.quiz_id
            )
        )
        if question is None:
            raise ResourceNotFoundError("Question", str(question_id))

        if question.question_type is not QuestionType.MCQ:
            raise AnchorError(
                "This question expects a written answer, not a chosen option."
            )
        if not (0 <= selected_index < OPTIONS_PER_QUESTION):
            raise AnchorError("That answer option does not exist.")

        correct = selected_index == question.correct_index

        existing = self.session.scalar(
            select(QuizAnswer).where(
                QuizAnswer.attempt_id == attempt.id,
                QuizAnswer.question_id == question.id,
            )
        )
        if existing is not None:
            # Re-answering before submission replaces the previous choice. Mastery
            # is not applied twice: it was applied on the first answer, and
            # re-crediting would let a student farm a topic by toggling options.
            existing.selected_index = selected_index
            existing.is_correct = correct
            self.session.commit()
            self.session.refresh(existing)
            return existing, question

        answer = QuizAnswer(
            attempt_id=attempt.id,
            question_id=question.id,
            selected_index=selected_index,
            is_correct=correct,
            answered_in_seconds=answered_in_seconds,
        )
        self.session.add(answer)

        quiz = self.session.get(Quiz, attempt.quiz_id)
        if quiz is not None:
            self.mastery.record_answer(
                user_id=user_id,
                course_id=quiz.course_id,
                topic_id=question.topic_id,
                difficulty=question.difficulty,
                correct=correct,
                source_id=answer.id if answer.id else None,
            )

        self.session.commit()
        self.session.refresh(answer)
        return answer, question

    def record_short_answer(
        self,
        *,
        user_id: uuid.UUID,
        attempt_id: uuid.UUID,
        question_id: uuid.UUID,
        response_text: str,
        answered_in_seconds: int | None = None,
    ) -> tuple[QuizAnswer, QuizQuestion, GradingResult]:
        """Record and grade one written answer.

        Grading happens inline rather than in a background job: the student is
        waiting for feedback, and a queue would mean showing them an answer with no
        verdict. The trade-off is one model call in the request path, which is why
        `grade` never raises — a provider failure returns FAILED and the answer is
        stored anyway.

        Mastery follows the same rule as multiple choice: it is applied once, on the
        first answer. Re-answering before submission updates the verdict and the
        feedback but does not credit the topic again, so a student cannot farm
        mastery by resubmitting.
        """
        attempt = self.get_attempt(user_id, attempt_id)
        if attempt.is_complete:
            raise AnchorError("This attempt has already been submitted.")

        question = self.session.scalar(
            select(QuizQuestion).where(
                QuizQuestion.id == question_id, QuizQuestion.quiz_id == attempt.quiz_id
            )
        )
        if question is None:
            raise ResourceNotFoundError("Question", str(question_id))
        if question.question_type is not QuestionType.SHORT_ANSWER:
            raise AnchorError("This question expects one of the given options.")
        if not response_text or not response_text.strip():
            raise AnchorError("Write an answer before submitting it.")

        result = self.grader.grade(question, response_text)

        existing = self.session.scalar(
            select(QuizAnswer).where(
                QuizAnswer.attempt_id == attempt.id,
                QuizAnswer.question_id == question.id,
            )
        )
        if existing is not None:
            _write_grade(existing, response_text, result)
            self.session.commit()
            self.session.refresh(existing)
            return existing, question, result

        answer = QuizAnswer(
            attempt_id=attempt.id,
            question_id=question.id,
            answered_in_seconds=answered_in_seconds,
        )
        _write_grade(answer, response_text, result)
        self.session.add(answer)

        quiz = self.session.get(Quiz, attempt.quiz_id)
        # An `uncertain` verdict, and a grading failure, both leave mastery alone.
        if quiz is not None and result.affects_mastery and result.outcome is not None:
            self.mastery.record_short_answer(
                user_id=user_id,
                course_id=quiz.course_id,
                topic_id=question.topic_id,
                difficulty=question.difficulty,
                verdict=result.outcome.verdict,
                source_id=answer.id if answer.id else None,
            )

        self.session.commit()
        self.session.refresh(answer)
        return answer, question, result

    def complete_attempt(self, user_id: uuid.UUID, attempt_id: uuid.UUID) -> QuizAttempt:
        attempt = self.get_attempt(user_id, attempt_id)
        if attempt.is_complete:
            return attempt

        questions = {
            question.id: question
            for question in self.get(user_id, attempt.quiz_id).questions
        }
        answers = list(
            self.session.scalars(
                select(QuizAnswer).where(QuizAnswer.attempt_id == attempt.id)
            )
        )

        verdicts = [
            _verdict_of(answer, questions.get(answer.question_id)) for answer in answers
        ]
        # Skipping is not the same as getting it right, so unanswered questions
        # stay in the denominator. An answer nobody could mark does not.
        score = score_attempt(verdicts, unanswered=max(0, len(questions) - len(answers)))

        # Whole correct answers only. A partially correct answer earns half credit
        # towards the score but is not "a question you got right".
        attempt.correct_count = sum(
            1 for verdict in verdicts if verdict is AnswerVerdict.CORRECT
        )
        attempt.score_percent = score.percent
        attempt.completed_at = datetime.now(UTC)

        self.session.commit()
        self.session.refresh(attempt)
        return attempt

    def recent_attempts(
        self, user_id: uuid.UUID, course_id: uuid.UUID, limit: int = 10
    ) -> list[QuizAttempt]:
        self._assert_course_owned(user_id, course_id)
        return list(
            self.session.scalars(
                select(QuizAttempt)
                .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
                .where(
                    Quiz.course_id == course_id,
                    QuizAttempt.user_id == user_id,
                    QuizAttempt.completed_at.is_not(None),
                )
                .order_by(QuizAttempt.completed_at.desc())
                .limit(limit)
            )
        )

    def _assert_course_owned(self, user_id: uuid.UUID, course_id: uuid.UUID) -> Course:
        course = self.session.scalar(
            select(Course).where(Course.id == course_id, Course.user_id == user_id)
        )
        if course is None:
            raise ResourceNotFoundError("Course", str(course_id))
        return course


def _clean_concepts(raw: object) -> list[str]:
    """Trim and deduplicate the rubric points, preserving the model's order."""
    if not isinstance(raw, list):
        return []
    concepts: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        concept = " ".join(item.split())
        if not (MIN_CONCEPT_CHARS <= len(concept) <= MAX_CONCEPT_CHARS):
            continue
        key = concept.casefold()
        if key in seen:
            continue
        seen.add(key)
        concepts.append(concept)
    return concepts


def _split_by_format(
    plan: list[tuple[Topic, dict[Difficulty, int]]], quiz_format: QuizFormat
) -> list[tuple[Topic, dict[Difficulty, int], dict[Difficulty, int]]]:
    """Divide an existing topic/difficulty plan between the two question formats.

    The split happens after topic selection, so the adaptive engine's decisions are
    untouched by which formats were requested — a weak topic gets the same share of
    the quiz whether that share is multiple choice or written.

    In MIXED mode the short-answer allocation is taken hardest-first: if only some
    questions can be written ones, they should be the questions where explaining
    the answer is worth more than recognising it.
    """
    if quiz_format is QuizFormat.MCQ:
        return [(topic, counts, {}) for topic, counts in plan]
    if quiz_format is QuizFormat.SHORT_ANSWER:
        return [(topic, {}, counts) for topic, counts in plan]

    total = sum(sum(counts.values()) for _, counts in plan)
    # At least one of each, so a "mixed" quiz is never secretly single-format.
    wanted_short = min(max(1, round(total * SHORT_ANSWER_SHARE)), max(0, total - 1))

    # Difficulty is the OUTER loop, so the hardest questions across the whole quiz
    # are converted first. Looping topics first would spend the entire short-answer
    # budget on whichever topic happened to sort earliest.
    short_counts: dict[int, dict[Difficulty, int]] = {
        index: {} for index in range(len(plan))
    }
    remaining = wanted_short
    for level in (Difficulty.HARD, Difficulty.MEDIUM, Difficulty.EASY):
        for index, (_, counts) in enumerate(plan):
            if remaining <= 0:
                break
            take = min(counts.get(level, 0), remaining)
            if take:
                short_counts[index][level] = take
                remaining -= take

    split: list[tuple[Topic, dict[Difficulty, int], dict[Difficulty, int]]] = []
    for index, (topic, counts) in enumerate(plan):
        taken = short_counts[index]
        mcq_counts = {
            level: count - taken.get(level, 0)
            for level, count in counts.items()
            if count - taken.get(level, 0) > 0
        }
        split.append((topic, mcq_counts, taken))
    return split


def _write_grade(answer: QuizAnswer, response_text: str, result: GradingResult) -> None:
    """Copy a grading result onto the answer row.

    The response is stored verbatim regardless of outcome — including when grading
    failed, which is what makes a later regrade possible.
    """
    answer.response_text = response_text
    answer.grading_state = result.state
    answer.grader_model = result.grader_model
    answer.graded_at = GradingService.graded_at()

    if result.outcome is None:
        answer.verdict = None
        answer.is_correct = None
        answer.rubric_results = None
        answer.feedback = None
        return

    answer.verdict = result.outcome.verdict
    answer.is_correct = result.outcome.is_correct
    answer.rubric_results = result.outcome.as_rubric_rows()
    answer.feedback = result.outcome.feedback


def _verdict_of(
    answer: QuizAnswer, question: QuizQuestion | None
) -> AnswerVerdict | None:
    """Map one stored answer onto a verdict for scoring.

    None means "leave it out of the denominator", which covers a short answer whose
    grading failed. A multiple-choice answer always has a verdict.
    """
    if question is not None and question.question_type is QuestionType.SHORT_ANSWER:
        if answer.grading_state is not GradingState.GRADED:
            return None
        return answer.verdict
    return AnswerVerdict.CORRECT if answer.is_correct else AnswerVerdict.INCORRECT


def _rationale_for(selected) -> str:
    """Explain the adaptive choice in the student's language, from templates.

    Deterministic string building, not an LLM call — this text is shown on every
    generated quiz and must not cost quota.
    """
    focus = [item for item in selected if not item.is_review]
    review = [item for item in selected if item.is_review]

    parts: list[str] = []
    weak = [item.name for item in focus if item.band in ("needs_practice", "not_started")]
    developing = [item.name for item in focus if item.band == "developing"]

    if weak:
        parts.append(f"{_join(weak)} currently need more practice")
    if developing:
        parts.append(f"{_join(developing)} are still developing")
    if review:
        parts.append(f"{_join([item.name for item in review])} is included for review")

    if not parts:
        return "Selected to give you a spread across this course."
    return "Selected because " + "; ".join(parts) + "."


def _join(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f" and {names[-1]}"


def _exam_rationale(selected, days_remaining: int | None) -> str:
    """Explain the exam-mode selection, from templates."""
    names = _join([item.name for item in selected])

    if days_remaining is None:
        return f"Exam preparation across {names}."
    if days_remaining < 0:
        return f"Your exam date has passed. Covering {names} for revision."
    if days_remaining == 0:
        return f"Your exam is today. Covering {names}."
    day_word = "day" if days_remaining == 1 else "days"
    return (
        f"{days_remaining} {day_word} until your exam. Prioritising {names} "
        "for coverage and weak areas."
    )
