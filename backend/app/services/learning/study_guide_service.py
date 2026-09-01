"""Generating and reading a course's study guide.

WHY IT IS STORED
================

A guide costs one model call per topic plus one to synthesise them. Regenerating
that on every page view would be indefensible, so the guide is written once and
read back. Regeneration is always something the student asks for.

HIERARCHICAL GENERATION
=======================

    per topic:  retrieve that topic's chunks -> one grounded call -> a section
    once:       all the section summaries    -> one call          -> the overview

n topics is n+1 calls. The alternative — one prompt containing the whole course —
does not fit in a context window for a real course, and what it produced would be
grounded in whichever excerpts survived truncation rather than in the course.

Only the per-topic calls see excerpts, so only they cite. The overview is written
from summaries and carries no citations, because it has nothing first-hand to cite.

STALENESS
=========

The guide records a fingerprint of the material it was built from: the ready
documents, their chunk counts, and the active topic set. On read, that is compared
with the course as it stands now. A mismatch marks the guide STALE — still
readable, clearly labelled, and regenerable on request. It is never silently
regenerated (that would spend the student's quota without asking) and never
silently served as current (that would be a lie about provenance).

WHAT IS NOT STORED HERE
=======================

Mastery. The student's progress is overlaid at read time from the mastery services,
so the guide's text stays put while their progress moves. Freezing a mastery badge
into generated prose would make the guide wrong the moment they answered a question.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.clock import now
from app.core.config import settings
from app.core.exceptions import ResourceNotFoundError
from app.models import (
    Course,
    StudyGuide,
    StudyGuideSection,
    StudyGuideSectionSource,
    StudyGuideStatus,
    Topic,
)
from app.services.learning.grounding import (
    GroundingContext,
    InsufficientMaterialError,
    build_grounding_context,
)
from app.services.learning.mastery_service import MasteryService
from app.services.learning.material import material_and_topics_fingerprint
from app.services.learning.prompts import (
    MAX_SECTION_KEY_CONCEPTS,
    MAX_SECTION_KEY_TERMS,
    STUDY_GUIDE_OVERVIEW_SCHEMA,
    STUDY_GUIDE_OVERVIEW_SYSTEM,
    STUDY_GUIDE_SECTION_SCHEMA,
    STUDY_GUIDE_SECTION_SYSTEM,
    study_guide_overview_prompt,
    study_guide_section_prompt,
)
from app.services.rag.embeddings import EmbeddingProvider
from app.services.rag.generation import ChatMessage, GenerationError, LLMProvider
from app.services.rag.retrieval import RetrievalService, RetrievedChunk

# Chunks per topic. Wider than quiz generation: a section summarises a topic rather
# than testing one point of it.
CHUNKS_PER_SECTION = 8

# A guide of one section is a section, not a guide.
MIN_SECTIONS = 1

MIN_SUMMARY_CHARS = 40
MAX_SUMMARY_CHARS = 2_000
MAX_OVERVIEW_CHARS = 2_000
MIN_TERM_CHARS = 2
MAX_TERM_CHARS = 80
MIN_DEFINITION_CHARS = 10
MAX_DEFINITION_CHARS = 400
MAX_CONCEPT_CHARS = 300

# Key terms shown at the top of the guide, gathered from the sections.
MAX_GUIDE_KEY_TERMS = 12


@dataclass(frozen=True)
class SectionDraft:
    topic: Topic
    summary: str
    key_concepts: list[str]
    key_terms: list[dict]
    sources: list[RetrievedChunk]


class StudyGuideService:
    def __init__(
        self, session: Session, embeddings: EmbeddingProvider, llm: LLMProvider
    ) -> None:
        self.session = session
        self.embeddings = embeddings
        self.llm = llm
        self.retrieval = RetrievalService(session)
        self.mastery = MasteryService(session)

    # --- Reading ---------------------------------------------------------------

    def get(self, user_id: uuid.UUID, course_id: uuid.UUID) -> StudyGuide | None:
        """The stored guide, with its staleness re-checked against the course.

        Marking stale is a write, so it is committed here rather than computed for
        display only — otherwise every read would recompute the same conclusion and
        the stored status would drift from what the student is shown.
        """
        self._assert_course_owned(user_id, course_id)

        guide = self.session.scalar(
            select(StudyGuide)
            .where(StudyGuide.user_id == user_id, StudyGuide.course_id == course_id)
            .options(
                selectinload(StudyGuide.sections).selectinload(StudyGuideSection.sources),
                selectinload(StudyGuide.sections).selectinload(StudyGuideSection.topic),
            )
        )
        if guide is None:
            return None

        if guide.status is StudyGuideStatus.READY and (
            guide.material_fingerprint != self._fingerprint(course_id)
        ):
            guide.status = StudyGuideStatus.STALE
            self.session.commit()
            self.session.refresh(guide)

        return guide

    # --- Generation ------------------------------------------------------------

    def generate(self, user_id: uuid.UUID, course_id: uuid.UUID) -> StudyGuide:
        """(Re)build the guide for one course."""
        course = self._assert_course_owned(user_id, course_id)

        topics = list(
            self.session.scalars(
                select(Topic)
                .where(Topic.course_id == course_id, Topic.is_active.is_(True))
                .order_by(Topic.name)
            )
        )
        if not topics:
            raise InsufficientMaterialError(
                "This course has no topics yet. Extract topics before building a "
                "study guide."
            )

        guide = self._guide_row(user_id, course_id)
        guide.status = StudyGuideStatus.GENERATING
        guide.error_message = None
        self.session.commit()

        try:
            drafts = [
                draft
                for topic in topics
                if (draft := self._draft_section(user_id, course_id, topic)) is not None
            ]
            if len(drafts) < MIN_SECTIONS:
                raise InsufficientMaterialError(
                    "There is not enough processed material to write a study guide "
                    "for this course yet."
                )
            overview = self._synthesise(course.title, drafts)
        except InsufficientMaterialError as error:
            self._fail(guide, str(error))
            raise
        except GenerationError as error:
            self._fail(guide, str(error))
            raise

        return self._store(guide, course_id, overview, drafts)

    # --- Per-topic sections ----------------------------------------------------

    def _draft_section(
        self, user_id: uuid.UUID, course_id: uuid.UUID, topic: Topic
    ) -> SectionDraft | None:
        """One grounded call for one topic. None when the topic has no material.

        A topic that cannot be sourced is skipped rather than written from general
        knowledge, so the guide covers less than the syllabus rather than covering
        it wrongly.
        """
        query = f"{topic.name}. {topic.description}".strip()
        chunks = self.retrieval.search(
            user_id,
            course_id,
            self.embeddings.embed_query(query),
            top_k=CHUNKS_PER_SECTION,
            min_similarity=settings.RAG_MIN_SIMILARITY,
        )
        if not chunks:
            return None

        context = build_grounding_context(chunks)
        try:
            raw = self.llm.generate_json(
                [
                    ChatMessage(role="system", content=STUDY_GUIDE_SECTION_SYSTEM),
                    ChatMessage(
                        role="user",
                        content=study_guide_section_prompt(
                            topic.name, topic.description, context.text
                        ),
                    ),
                ],
                STUDY_GUIDE_SECTION_SCHEMA,
            )
        except GenerationError:
            # One topic failing should not lose the rest of the guide.
            return None

        return self._validate_section(raw, topic, context)

    def _validate_section(
        self, raw: object, topic: Topic, context: GroundingContext
    ) -> SectionDraft | None:
        """Stage four for a section: every citation must resolve to a real chunk."""
        if not isinstance(raw, dict):
            return None

        summary = " ".join(str(raw.get("summary") or "").split())
        if not (MIN_SUMMARY_CHARS <= len(summary) <= MAX_SUMMARY_CHARS):
            return None

        concepts: list[str] = []
        seen_concepts: set[str] = set()
        for item in raw.get("key_concepts") or []:
            if not isinstance(item, str):
                continue
            concept = " ".join(item.split())
            key = concept.casefold()
            if not concept or len(concept) > MAX_CONCEPT_CHARS or key in seen_concepts:
                continue
            seen_concepts.add(key)
            concepts.append(concept)
            if len(concepts) >= MAX_SECTION_KEY_CONCEPTS:
                break

        # Sources are the excerpts the model says it used, intersected with the
        # excerpts we supplied. A number outside that range cites nothing.
        sources: list[RetrievedChunk] = []
        seen_chunks: set[uuid.UUID] = set()
        for number in raw.get("excerpt_numbers") or []:
            if not isinstance(number, int):
                continue
            chunk = context.resolve(number)
            if chunk is None or chunk.chunk_id in seen_chunks:
                continue
            seen_chunks.add(chunk.chunk_id)
            sources.append(chunk)

        if not sources:
            # A section with no resolvable provenance is exactly the thing this
            # project promises not to show.
            return None

        terms: list[dict] = []
        seen_terms: set[str] = set()
        for item in raw.get("key_terms") or []:
            if not isinstance(item, dict):
                continue
            term = " ".join(str(item.get("term") or "").split())
            definition = " ".join(str(item.get("definition") or "").split())
            number = item.get("excerpt_number")
            if not (MIN_TERM_CHARS <= len(term) <= MAX_TERM_CHARS):
                continue
            if not (MIN_DEFINITION_CHARS <= len(definition) <= MAX_DEFINITION_CHARS):
                continue
            if not isinstance(number, int):
                continue
            chunk = context.resolve(number)
            if chunk is None or term.casefold() in seen_terms:
                continue
            seen_terms.add(term.casefold())
            # The excerpt number is resolved here and thrown away: it means nothing
            # outside the prompt that produced it, whereas a chunk id is permanent.
            terms.append(
                {
                    "term": term,
                    "definition": definition,
                    "chunk_id": str(chunk.chunk_id),
                    "document_id": str(chunk.document_id),
                }
            )
            if len(terms) >= MAX_SECTION_KEY_TERMS:
                break

        return SectionDraft(
            topic=topic,
            summary=summary,
            key_concepts=concepts,
            key_terms=terms,
            sources=sources,
        )

    # --- Synthesis -------------------------------------------------------------

    def _synthesise(self, course_title: str, drafts: list[SectionDraft]) -> str:
        """The single call that turns the sections into a course overview."""
        summaries = "\n\n".join(
            f"{draft.topic.name}: {draft.summary}" for draft in drafts
        )
        raw = self.llm.generate_json(
            [
                ChatMessage(role="system", content=STUDY_GUIDE_OVERVIEW_SYSTEM),
                ChatMessage(
                    role="user",
                    content=study_guide_overview_prompt(course_title, summaries),
                ),
            ],
            STUDY_GUIDE_OVERVIEW_SCHEMA,
        )
        overview = ""
        if isinstance(raw, dict):
            overview = " ".join(str(raw.get("overview") or "").split())
        if len(overview) > MAX_OVERVIEW_CHARS:
            overview = overview[:MAX_OVERVIEW_CHARS].rstrip()
        # An empty overview is survivable — the sections carry the guide, and
        # failing the whole thing over its introduction would be disproportionate.
        return overview

    # --- Persistence -----------------------------------------------------------

    def _store(
        self,
        guide: StudyGuide,
        course_id: uuid.UUID,
        overview: str,
        drafts: list[SectionDraft],
    ) -> StudyGuide:
        # Replacing the sections outright: they are derived text, and a partial
        # update would leave a guide half from one generation and half from another.
        guide.sections.clear()
        self.session.flush()

        key_terms: list[dict] = []
        seen_terms: set[str] = set()

        for position, draft in enumerate(drafts):
            section = StudyGuideSection(
                topic_id=draft.topic.id,
                position=position,
                summary=draft.summary,
                key_concepts=draft.key_concepts,
            )
            section.sources = [
                StudyGuideSectionSource(
                    chunk_id=chunk.chunk_id, document_id=chunk.document_id
                )
                for chunk in draft.sources
            ]
            guide.sections.append(section)

            for term in draft.key_terms:
                key = term["term"].casefold()
                if key in seen_terms or len(key_terms) >= MAX_GUIDE_KEY_TERMS:
                    continue
                seen_terms.add(key)
                key_terms.append(term)

        guide.overview = overview
        guide.key_terms = key_terms
        guide.status = StudyGuideStatus.READY
        guide.generated_at = now()
        guide.material_fingerprint = self._fingerprint(course_id)
        guide.error_message = None

        self.session.commit()
        self.session.refresh(guide)
        return guide

    def _fail(self, guide: StudyGuide, message: str) -> None:
        guide.status = StudyGuideStatus.FAILED
        guide.error_message = message[:500]
        self.session.commit()

    def _guide_row(self, user_id: uuid.UUID, course_id: uuid.UUID) -> StudyGuide:
        guide = self.session.scalar(
            select(StudyGuide).where(
                StudyGuide.user_id == user_id, StudyGuide.course_id == course_id
            )
        )
        if guide is None:
            guide = StudyGuide(user_id=user_id, course_id=course_id)
            self.session.add(guide)
            self.session.flush()
        return guide

    # --- Staleness -------------------------------------------------------------

    def _fingerprint(self, course_id: uuid.UUID) -> str:
        """A digest of what the guide would be built from right now.

        Covers the READY documents *and* the active topics, because a section is
        written per topic: the guide is stale when either moves. Shared with topic
        sync so the two cannot drift apart — see services/learning/material.py.
        """
        return material_and_topics_fingerprint(self.session, course_id)

    def _assert_course_owned(self, user_id: uuid.UUID, course_id: uuid.UUID) -> Course:
        course = self.session.scalar(
            select(Course).where(Course.id == course_id, Course.user_id == user_id)
        )
        if course is None:
            raise ResourceNotFoundError("Course", str(course_id))
        return course
