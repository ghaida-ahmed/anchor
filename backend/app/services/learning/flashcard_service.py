"""Grounded flashcard generation.

Same pipeline as quizzes — retrieve, generate from those excerpts only, validate,
persist — with a simpler shape. Cards are stored so opening the tab costs nothing;
regenerating identical cards on every page load would burn free-tier quota for no
benefit.

There is deliberately no scheduling state. Spaced repetition needs review history,
intervals and a due-date query, and half of it would be dead weight until the review
UI exists.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ResourceNotFoundError
from app.models import Course, Flashcard, Topic
from app.services.learning.adaptive import priority_for
from app.services.learning.grounding import (
    InsufficientMaterialError,
    build_grounding_context,
)
from app.services.learning.mastery_service import MasteryService
from app.services.learning.prompts import (
    FLASHCARD_SCHEMA,
    FLASHCARD_SYSTEM,
    flashcard_prompt,
)
from app.services.rag.embeddings import EmbeddingProvider
from app.services.rag.generation import ChatMessage, LLMProvider
from app.services.rag.retrieval import RetrievalService

CHUNKS_PER_TOPIC = 6
CARDS_PER_TOPIC = 5
MAX_TOPICS_PER_REQUEST = 4
MAX_FRONT_CHARS = 300
MAX_BACK_CHARS = 1200


@dataclass(frozen=True)
class _ValidatedCard:
    front: str
    back: str
    topic_id: uuid.UUID
    chunk_id: uuid.UUID
    document_id: uuid.UUID


class FlashcardService:
    def __init__(
        self, session: Session, embeddings: EmbeddingProvider, llm: LLMProvider
    ) -> None:
        self.session = session
        self.embeddings = embeddings
        self.llm = llm
        self.retrieval = RetrievalService(session)
        self.mastery = MasteryService(session)

    def list_for_course(
        self, user_id: uuid.UUID, course_id: uuid.UUID, topic_id: uuid.UUID | None = None
    ) -> list[Flashcard]:
        self._assert_course_owned(user_id, course_id)

        query = (
            select(Flashcard)
            .where(Flashcard.course_id == course_id, Flashcard.user_id == user_id)
            .order_by(Flashcard.created_at.desc())
        )
        if topic_id is not None:
            query = query.where(Flashcard.topic_id == topic_id)

        return list(self.session.scalars(query))

    def generate(
        self,
        *,
        user_id: uuid.UUID,
        course_id: uuid.UUID,
        topic_ids: list[uuid.UUID] | None = None,
        weak_topics_only: bool = False,
        replace_existing: bool = True,
    ) -> list[Flashcard]:
        self._assert_course_owned(user_id, course_id)
        topics = self._choose_topics(user_id, course_id, topic_ids, weak_topics_only)

        if not topics:
            raise InsufficientMaterialError(
                "This course has no topics yet. Extract topics before generating "
                "flashcards."
            )

        cards: list[_ValidatedCard] = []
        for topic in topics:
            cards.extend(self._generate_for_topic(user_id, course_id, topic))

        if not cards:
            raise InsufficientMaterialError(
                "Not enough information in your course materials to generate "
                "flashcards for these topics."
            )

        if replace_existing:
            # Regenerating a topic replaces its cards rather than accumulating
            # near-duplicates across runs.
            self.session.execute(
                delete(Flashcard).where(
                    Flashcard.user_id == user_id,
                    Flashcard.course_id == course_id,
                    Flashcard.topic_id.in_([topic.id for topic in topics]),
                )
            )

        created = [
            Flashcard(
                user_id=user_id,
                course_id=course_id,
                topic_id=card.topic_id,
                front=card.front,
                back=card.back,
                source_chunk_id=card.chunk_id,
                source_document_id=card.document_id,
            )
            for card in cards
        ]
        self.session.add_all(created)
        self.session.commit()
        for card in created:
            self.session.refresh(card)

        return created

    def _choose_topics(
        self,
        user_id: uuid.UUID,
        course_id: uuid.UUID,
        topic_ids: list[uuid.UUID] | None,
        weak_topics_only: bool,
    ) -> list[Topic]:
        if weak_topics_only:
            # Same deterministic priority the adaptive quiz uses — no LLM decides
            # what is weak.
            candidates = self.mastery.candidates_for(user_id, course_id)
            ranked = sorted(candidates, key=lambda c: (-priority_for(c), c.name.lower()))[
                :MAX_TOPICS_PER_REQUEST
            ]
            wanted = [candidate.topic_id for candidate in ranked]
        else:
            wanted = topic_ids or []

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
        if wanted:
            query = query.where(Topic.id.in_(wanted))

        return list(self.session.scalars(query))[:MAX_TOPICS_PER_REQUEST]

    def _generate_for_topic(
        self, user_id: uuid.UUID, course_id: uuid.UUID, topic: Topic
    ) -> list[_ValidatedCard]:
        query = f"{topic.name}. {topic.description}".strip()
        chunks = self.retrieval.search(
            user_id,
            course_id,
            self.embeddings.embed_query(query),
            top_k=CHUNKS_PER_TOPIC,
            min_similarity=settings.RAG_MIN_SIMILARITY,
        )
        if not chunks:
            return []

        context = build_grounding_context(chunks)
        raw = self.llm.generate_json(
            [
                ChatMessage(role="system", content=FLASHCARD_SYSTEM),
                ChatMessage(
                    role="user",
                    content=flashcard_prompt(topic.name, CARDS_PER_TOPIC, context.text),
                ),
            ],
            FLASHCARD_SCHEMA,
        )

        if not isinstance(raw, dict) or not isinstance(raw.get("cards"), list):
            return []

        validated: list[_ValidatedCard] = []
        seen: set[str] = set()

        for item in raw["cards"][:CARDS_PER_TOPIC]:
            if not isinstance(item, dict):
                continue
            front = str(item.get("front") or "").strip()[:MAX_FRONT_CHARS]
            back = str(item.get("back") or "").strip()[:MAX_BACK_CHARS]
            excerpt = item.get("excerpt_number")

            if not front or not back or front.lower() in seen:
                continue
            if not isinstance(excerpt, int):
                continue

            chunk = context.resolve(excerpt)
            if chunk is None:
                # Cited an excerpt we did not supply — provenance would be invented.
                continue

            seen.add(front.lower())
            validated.append(
                _ValidatedCard(
                    front=front,
                    back=back,
                    topic_id=topic.id,
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                )
            )

        return validated

    def _assert_course_owned(self, user_id: uuid.UUID, course_id: uuid.UUID) -> None:
        owned = self.session.scalar(
            select(Course.id).where(Course.id == course_id, Course.user_id == user_id)
        )
        if owned is None:
            raise ResourceNotFoundError("Course", str(course_id))
