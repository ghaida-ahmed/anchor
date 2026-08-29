/**
 * Knowledge map and knowledge-gap client.
 *
 * Reading never generates: `fetchKnowledgeMap` is a GET and comes back empty for a
 * course whose map has not been built. Generation is an explicit POST because it
 * costs model calls.
 */

import { apiRequest } from '@/services/api/client';
import type { QuizSource } from '@/services/api/learning';
import type { ISODateString } from '@/types/domain';

/* -------------------------------------------------------------------------- */
/*  Wire types                                                                 */
/* -------------------------------------------------------------------------- */

interface SourceDto {
  document_id: string;
  document_name: string;
  page_number: number | null;
  chunk_id: string;
}

interface NodeDto {
  topic_id: string;
  name: string;
  description: string;
  mastery: number;
  effective_mastery: number;
  band: string;
  band_label: string;
  questions_attempted: number;
}

interface EdgeDto {
  id: string;
  source_topic_id: string;
  target_topic_id: string;
  relationship_type: RelationshipType;
  supporting_chunk_count: number;
  sources: SourceDto[];
}

interface MapDto {
  course_id: string;
  nodes: NodeDto[];
  edges: EdgeDto[];
  generated_at: ISODateString | null;
}

interface GenerateMapDto extends MapDto {
  candidates_rejected: number;
  model_calls: number;
}

interface GapDto {
  topic_id: string;
  name: string;
  kind: GapKind;
  kind_label: string;
  severity: number;
  effective_mastery: number;
  blocked_topics: string[];
  attempted_dependents: string[];
  reason: string;
}

interface GapsDto {
  course_id: string;
  gaps: GapDto[];
  has_map: boolean;
}

/* -------------------------------------------------------------------------- */
/*  Domain types                                                               */
/* -------------------------------------------------------------------------- */

/** `prerequisite` is directed (source must come first); `related` is not. */
export type RelationshipType = 'prerequisite' | 'related';

export type GapKind = 'unmet_prerequisite' | 'blocking' | 'isolated';

export interface KnowledgeNode {
  topicId: string;
  name: string;
  description: string;
  mastery: number;
  /** Mastery after the retention heuristic — what the map colours by. */
  effectiveMastery: number;
  band: string;
  bandLabel: string;
  questionsAttempted: number;
}

export interface KnowledgeEdge {
  id: string;
  sourceTopicId: string;
  targetTopicId: string;
  relationshipType: RelationshipType;
  /**
   * How many excerpts support this link. A count of evidence we hold, NOT a
   * confidence the model reported — the UI says "supported by N excerpts" so the
   * number means exactly what it is.
   */
  supportingChunkCount: number;
  sources: QuizSource[];
}

export interface KnowledgeMap {
  courseId: string;
  nodes: KnowledgeNode[];
  edges: KnowledgeEdge[];
  generatedAt: ISODateString | null;
}

export interface KnowledgeMapGeneration extends KnowledgeMap {
  candidatesRejected: number;
  modelCalls: number;
}

export interface KnowledgeGap {
  topicId: string;
  name: string;
  kind: GapKind;
  kindLabel: string;
  /** 0–1. Deterministic; see backend/app/services/learning/knowledge.py. */
  severity: number;
  effectiveMastery: number;
  blockedTopics: string[];
  attemptedDependents: string[];
  reason: string;
}

export interface KnowledgeGaps {
  courseId: string;
  gaps: KnowledgeGap[];
  /** False when no map has been generated — gaps still work, with less context. */
  hasMap: boolean;
}

/* -------------------------------------------------------------------------- */
/*  Mapping                                                                    */
/* -------------------------------------------------------------------------- */

function toSource(dto: SourceDto): QuizSource {
  return {
    documentId: dto.document_id,
    documentName: dto.document_name,
    pageNumber: dto.page_number,
    chunkId: dto.chunk_id,
  };
}

function toNode(dto: NodeDto): KnowledgeNode {
  return {
    topicId: dto.topic_id,
    name: dto.name,
    description: dto.description,
    mastery: dto.mastery,
    effectiveMastery: dto.effective_mastery,
    band: dto.band,
    bandLabel: dto.band_label,
    questionsAttempted: dto.questions_attempted,
  };
}

function toEdge(dto: EdgeDto): KnowledgeEdge {
  return {
    id: dto.id,
    sourceTopicId: dto.source_topic_id,
    targetTopicId: dto.target_topic_id,
    relationshipType: dto.relationship_type,
    supportingChunkCount: dto.supporting_chunk_count,
    sources: dto.sources.map(toSource),
  };
}

function toMap(dto: MapDto): KnowledgeMap {
  return {
    courseId: dto.course_id,
    nodes: dto.nodes.map(toNode),
    edges: dto.edges.map(toEdge),
    generatedAt: dto.generated_at,
  };
}

function toGap(dto: GapDto): KnowledgeGap {
  return {
    topicId: dto.topic_id,
    name: dto.name,
    kind: dto.kind,
    kindLabel: dto.kind_label,
    severity: dto.severity,
    effectiveMastery: dto.effective_mastery,
    blockedTopics: dto.blocked_topics,
    attemptedDependents: dto.attempted_dependents,
    reason: dto.reason,
  };
}

/* -------------------------------------------------------------------------- */
/*  Requests                                                                   */
/* -------------------------------------------------------------------------- */

export async function fetchKnowledgeMap(courseId: string): Promise<KnowledgeMap> {
  return toMap(await apiRequest<MapDto>(`/v1/courses/${courseId}/knowledge-map`));
}

export async function generateKnowledgeMap(
  courseId: string,
): Promise<KnowledgeMapGeneration> {
  const dto = await apiRequest<GenerateMapDto>(
    `/v1/courses/${courseId}/knowledge-map`,
    { method: 'POST' },
  );
  return {
    ...toMap(dto),
    candidatesRejected: dto.candidates_rejected,
    modelCalls: dto.model_calls,
  };
}

export async function fetchKnowledgeGaps(courseId: string): Promise<KnowledgeGaps> {
  const dto = await apiRequest<GapsDto>(`/v1/courses/${courseId}/knowledge-gaps`);
  return {
    courseId: dto.course_id,
    gaps: dto.gaps.map(toGap),
    hasMap: dto.has_map,
  };
}
