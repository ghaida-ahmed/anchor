"""Deriving a course's topics from its uploaded material.

Topics come from retrieved document chunks, never from the course title — a course
called "Computer Networks" must not yield "Networking" unless the material actually
teaches it.

Regeneration is additive by design. Mastery rows reference topics, so deleting a
topic that no longer appears would destroy a student's history. Instead topics are
deactivated: they stop being offered for new quizzes but remain readable, and if
later uploads bring them back they are reactivated rather than duplicated.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ResourceNotFoundError
from app.models import (
    Course,
    Document,
    DocumentChunk,
    ProcessingStatus,
    Topic,
    normalise_topic_name,
)
from app.services.learning.grounding import (
    InsufficientMaterialError,
    build_grounding_context,
)
from app.services.learning.material import material_fingerprint
from app.services.learning.prompts import (
    TOPIC_EXTRACTION_SCHEMA,
    TOPIC_EXTRACTION_SYSTEM,
    topic_extraction_prompt,
)
from app.services.rag.generation import ChatMessage, LLMProvider
from app.services.rag.retrieval import RetrievedChunk

# Extraction reads a spread of the course rather than the top-k for one query:
# topics should cover the whole syllabus, not whatever matches a search.
MAX_CHUNKS_FOR_EXTRACTION = 40

# Below this there is not enough material to say anything useful about a course.
MIN_CHUNKS_FOR_EXTRACTION = 1

# Guards against a model returning a hundred near-identical topics.
MAX_TOPICS_PER_COURSE = 25

MIN_TOPIC_NAME_CHARS = 3
MAX_TOPIC_NAME_CHARS = 60

# Names that are structural rather than educational. Rejected outright.
_MEANINGLESS_NAMES = {
    "introduction",
    "overview",
    "summary",
    "conclusion",
    "contents",
    "agenda",
    "references",
    "bibliography",
    "appendix",
    "notes",
    "lecture",
    "chapter",
    "syllabus",
    "course",
}


@dataclass(frozen=True)
class TopicExtractionResult:
    created: list[Topic]
    reactivated: list[Topic]
    deactivated: list[Topic]
    unchanged: list[Topic]

    @property
    def active(self) -> list[Topic]:
        return [*self.created, *self.reactivated, *self.unchanged]


def _advisory_key(course_id: uuid.UUID | str) -> int:
    """A stable signed 64-bit key for `pg_try_advisory_xact_lock`.

    Postgres advisory locks are keyed by bigint, so the UUID is folded down. A
    collision between two courses would only ever cost one of them a skipped
    automatic sync, recoverable with "Update topics" — so 64 bits is ample.

    Accepts a string because course ids arrive from path parameters as well as
    from ORM columns, and a lock key that works in one caller and raises in the
    other is the kind of bug that only shows up under concurrency.
    """
    identifier = (
        course_id if isinstance(course_id, uuid.UUID) else uuid.UUID(str(course_id))
    )
    return int.from_bytes(identifier.bytes[:8], "big", signed=True)


class TopicService:
    def __init__(self, session: Session, llm: LLMProvider) -> None:
        self.session = session
        self.llm = llm

    def list_for_course(
        self, user_id: uuid.UUID, course_id: uuid.UUID, *, include_inactive: bool = False
    ) -> list[Topic]:
        self._assert_course_owned(user_id, course_id)

        query = select(Topic).where(Topic.course_id == course_id)
        if not include_inactive:
            query = query.where(Topic.is_active.is_(True))

        return list(self.session.scalars(query.order_by(Topic.name)))

    def extract(self, user_id: uuid.UUID, course_id: uuid.UUID) -> TopicExtractionResult:
        """(Re)derive the course's topics from its ready documents."""
        course = self._assert_course_owned(user_id, course_id)
        chunks = self._sample_course_chunks(course_id)

        if len(chunks) < MIN_CHUNKS_FOR_EXTRACTION:
            raise InsufficientMaterialError(
                "There is no processed course material to extract topics from. "
                "Upload a document and wait for it to finish processing."
            )

        context = build_grounding_context(chunks)
        raw = self.llm.generate_json(
            [
                ChatMessage(role="system", content=TOPIC_EXTRACTION_SYSTEM),
                ChatMessage(
                    role="user",
                    content=topic_extraction_prompt(course.title, context.text),
                ),
            ],
            TOPIC_EXTRACTION_SCHEMA,
        )

        proposed = self._validate(raw, course.title)
        if not proposed:
            raise InsufficientMaterialError(
                "No clear topics could be identified in this course's materials."
            )

        return self._reconcile(course_id, proposed)

    # --- Internals -------------------------------------------------------------

    def _sample_course_chunks(self, course_id: uuid.UUID) -> list[RetrievedChunk]:
        """Read a spread of chunks across the course's ready documents.

        Ordered by document then position so the sample follows the material's own
        structure — taking an arbitrary slice would bias topics towards whichever
        document happened to sort first.
        """
        rows = self.session.execute(
            select(
                DocumentChunk.id,
                DocumentChunk.document_id,
                Document.filename,
                DocumentChunk.page_number,
                DocumentChunk.chunk_index,
                DocumentChunk.content,
            )
            .join(Document, Document.id == DocumentChunk.document_id)
            .join(Course, Course.id == Document.course_id)
            .where(
                Course.id == course_id,
                Document.processing_status == ProcessingStatus.READY,
            )
            .order_by(Document.created_at, DocumentChunk.chunk_index)
            .limit(MAX_CHUNKS_FOR_EXTRACTION)
        ).all()

        return [
            RetrievedChunk(
                chunk_id=row.id,
                document_id=row.document_id,
                document_name=row.filename,
                page_number=row.page_number,
                chunk_index=row.chunk_index,
                content=row.content,
                # Not a similarity search; the score is not meaningful here.
                similarity=1.0,
            )
            for row in rows
        ]

    def _validate(self, raw: object, course_title: str) -> list[tuple[str, str]]:
        """Filter the model's proposals down to usable topics.

        Deduplicates on the normalised name, so "TCP Congestion Control" and "tcp
        congestion control" collapse to one.
        """
        if not isinstance(raw, dict):
            return []
        items = raw.get("topics")
        if not isinstance(items, list):
            return []

        course_normalised = normalise_topic_name(course_title)
        seen: set[str] = set()
        accepted: list[tuple[str, str]] = []

        for item in items:
            if not isinstance(item, dict):
                continue

            name = str(item.get("name") or "").strip()
            description = str(item.get("description") or "").strip()

            if not (MIN_TOPIC_NAME_CHARS <= len(name) <= MAX_TOPIC_NAME_CHARS):
                continue

            normalised = normalise_topic_name(name)
            if normalised in seen:
                continue
            # A topic that merely restates the course name teaches nothing.
            if normalised == course_normalised:
                continue
            if normalised in _MEANINGLESS_NAMES:
                continue

            seen.add(normalised)
            accepted.append((name, description[:1000]))

            if len(accepted) >= MAX_TOPICS_PER_COURSE:
                break

        return accepted

    def _reconcile(
        self, course_id: uuid.UUID, proposed: list[tuple[str, str]]
    ) -> TopicExtractionResult:
        """Merge proposals into the existing topic set without losing history."""
        existing = {
            topic.normalised_name: topic
            for topic in self.session.scalars(
                select(Topic).where(Topic.course_id == course_id)
            )
        }

        created: list[Topic] = []
        reactivated: list[Topic] = []
        unchanged: list[Topic] = []
        proposed_keys: set[str] = set()

        for name, description in proposed:
            key = normalise_topic_name(name)
            proposed_keys.add(key)
            topic = existing.get(key)

            if topic is None:
                topic = Topic(
                    course_id=course_id,
                    name=name,
                    normalised_name=key,
                    description=description,
                    is_active=True,
                )
                self.session.add(topic)
                created.append(topic)
                continue

            # Refresh the description; the newest material describes it best.
            topic.description = description or topic.description
            topic.name = name
            if topic.is_active:
                unchanged.append(topic)
            else:
                topic.is_active = True
                reactivated.append(topic)

        # Anything the material no longer supports is retired, not deleted: its
        # mastery rows and the attempts behind them stay intact.
        deactivated: list[Topic] = []
        for key, topic in existing.items():
            if key not in proposed_keys and topic.is_active:
                topic.is_active = False
                deactivated.append(topic)

        # Recorded in the same transaction as the topics themselves, so the
        # course can never claim to be in sync with material it did not extract
        # from — a crash between the two would otherwise leave exactly that lie.
        course = self.session.get(Course, course_id)
        if course is not None:
            course.topics_fingerprint = material_fingerprint(self.session, course_id)

        self.session.commit()
        for topic in [*created, *reactivated, *unchanged, *deactivated]:
            self.session.refresh(topic)

        return TopicExtractionResult(
            created=created,
            reactivated=reactivated,
            deactivated=deactivated,
            unchanged=unchanged,
        )

    # --- Keeping topics in step with the material ------------------------------

    def topics_are_current(self, course_id: uuid.UUID) -> bool:
        """Whether the topic set reflects the course's READY documents.

        A course with no processed material is always "current": there is nothing
        to extract from, so asking the student to update topics would be noise.
        """
        has_material = self.session.scalar(
            select(func.count(Document.id)).where(
                Document.course_id == course_id,
                Document.processing_status == ProcessingStatus.READY,
            )
        )
        if not has_material:
            return True

        course = self.session.get(Course, course_id)
        if course is None:
            return True
        return course.topics_fingerprint == material_fingerprint(self.session, course_id)

    def sync(self, user_id: uuid.UUID, course_id: uuid.UUID) -> bool:
        """Bring topics in line with the material, if they are not already.

        Returns whether an extraction actually ran. Safe to call repeatedly, and
        safe to call from two workers at once.

        CONCURRENCY. Two documents finishing together would otherwise both extract,
        racing on the `(course_id, normalised_name)` unique constraint and spending
        two Gemini calls for one result. A `SELECT ... FOR UPDATE` on the course row
        looks like the fix and is a trap: it BLOCKS, so a caller on a second
        connection waits behind any open transaction holding that row — which
        deadlocks the request that scheduled it.

        `pg_try_advisory_xact_lock` never blocks. It either takes the lock or
        reports that someone else has it, and that someone is by definition already
        doing this work, so skipping is correct rather than merely convenient. The
        lock is transaction-scoped, so it is released on commit or rollback without
        any cleanup path to forget.
        """
        if self.topics_are_current(course_id):
            return False

        acquired = self.session.scalar(
            select(func.pg_try_advisory_xact_lock(_advisory_key(course_id)))
        )
        if not acquired:
            return False

        # Re-check now the lock is held: a worker that finished between the first
        # check and here has already done this.
        if self.topics_are_current(course_id):
            return False

        self.extract(user_id, course_id)
        return True

    def _assert_course_owned(self, user_id: uuid.UUID, course_id: uuid.UUID) -> Course:
        course = self.session.scalar(
            select(Course).where(Course.id == course_id, Course.user_id == user_id)
        )
        if course is None:
            raise ResourceNotFoundError("Course", str(course_id))
        return course

    def count_active(self, course_id: uuid.UUID) -> int:
        return (
            self.session.scalar(
                select(func.count(Topic.id)).where(
                    Topic.course_id == course_id, Topic.is_active.is_(True)
                )
            )
            or 0
        )
