/**
 * Study guide client.
 *
 * A guide that has never been generated is a 404, not an empty object: "you have
 * not built one yet" and "we built one and it is empty" are different states and
 * the UI says different things about them.
 */

import { ApiError, apiRequest } from '@/services/api/client';
import type { QuizSource } from '@/services/api/learning';
import type { ISODateString } from '@/types/domain';

interface SourceDto {
  document_id: string;
  document_name: string;
  page_number: number | null;
  chunk_id: string;
}

interface KeyTermDto {
  term: string;
  definition: string;
  source: SourceDto | null;
}

interface SectionDto {
  topic_id: string;
  topic_name: string;
  position: number;
  summary: string;
  key_concepts: string[];
  sources: SourceDto[];
  mastery: number;
  effective_mastery: number;
  band: string;
  band_label: string;
  is_knowledge_gap: boolean;
}

interface StudyGuideDto {
  course_id: string;
  status: StudyGuideStatus;
  overview: string;
  key_terms: KeyTermDto[];
  sections: SectionDto[];
  generated_at: ISODateString | null;
  error_message: string | null;
  is_stale: boolean;
}

export type StudyGuideStatus =
  | 'not_generated'
  | 'generating'
  | 'ready'
  | 'stale'
  | 'failed';

export interface KeyTerm {
  term: string;
  definition: string;
  source: QuizSource | null;
}

export interface StudyGuideSection {
  topicId: string;
  topicName: string;
  position: number;
  summary: string;
  keyConcepts: string[];
  sources: QuizSource[];
  /** Overlaid at read time — the prose is about the material, this is about you. */
  mastery: number;
  effectiveMastery: number;
  band: string;
  bandLabel: string;
  isKnowledgeGap: boolean;
}

export interface StudyGuide {
  courseId: string;
  status: StudyGuideStatus;
  overview: string;
  keyTerms: KeyTerm[];
  sections: StudyGuideSection[];
  generatedAt: ISODateString | null;
  errorMessage: string | null;
  /** The material changed after generation. Still readable, no longer current. */
  isStale: boolean;
}

function toSource(dto: SourceDto | null): QuizSource | null {
  if (!dto) return null;
  return {
    documentId: dto.document_id,
    documentName: dto.document_name,
    pageNumber: dto.page_number,
    chunkId: dto.chunk_id,
  };
}

function toGuide(dto: StudyGuideDto): StudyGuide {
  return {
    courseId: dto.course_id,
    status: dto.status,
    overview: dto.overview,
    keyTerms: dto.key_terms.map((term) => ({
      term: term.term,
      definition: term.definition,
      source: toSource(term.source),
    })),
    sections: dto.sections.map((section) => ({
      topicId: section.topic_id,
      topicName: section.topic_name,
      position: section.position,
      summary: section.summary,
      keyConcepts: section.key_concepts,
      sources: section.sources
        .map(toSource)
        .filter((source): source is QuizSource => source !== null),
      mastery: section.mastery,
      effectiveMastery: section.effective_mastery,
      band: section.band,
      bandLabel: section.band_label,
      isKnowledgeGap: section.is_knowledge_gap,
    })),
    generatedAt: dto.generated_at,
    errorMessage: dto.error_message,
    isStale: dto.is_stale,
  };
}

/** Resolves to null when no guide has been generated for this course. */
export async function fetchStudyGuide(courseId: string): Promise<StudyGuide | null> {
  try {
    return toGuide(await apiRequest<StudyGuideDto>(`/v1/courses/${courseId}/study-guide`));
  } catch (caught) {
    // "Never generated" is a legitimate state for this tab, not an error to show.
    if (caught instanceof ApiError && caught.status === 404) return null;
    throw caught;
  }
}

export async function generateStudyGuide(courseId: string): Promise<StudyGuide> {
  return toGuide(
    await apiRequest<StudyGuideDto>(`/v1/courses/${courseId}/study-guide`, {
      method: 'POST',
    }),
  );
}
