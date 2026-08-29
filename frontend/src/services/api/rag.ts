import { apiRequest } from '@/services/api/client';

/** Wire shapes for the RAG endpoints, mapped into domain types below. */
interface SearchResultDto {
  chunk_id: string;
  document_id: string;
  document_name: string;
  page_number: number;
  chunk_index: number;
  content: string;
  similarity: number;
  distance: number;
}

interface SearchResponseDto {
  query: string;
  results: SearchResultDto[];
}

interface CitationDto {
  chunk_id: string;
  document_id: string;
  document_name: string;
  page_number: number;
  excerpt: string;
}

interface AskResponseDto {
  answer: string;
  citations: CitationDto[];
  is_grounded: boolean;
}

export interface SearchResult {
  chunkId: string;
  documentId: string;
  documentName: string;
  pageNumber: number;
  chunkIndex: number;
  content: string;
  similarity: number;
}

export interface Citation {
  chunkId: string;
  documentId: string;
  documentName: string;
  pageNumber: number;
  excerpt: string;
}

export interface TutorAnswer {
  answer: string;
  citations: Citation[];
  /** False when nothing relevant was retrieved and no model was consulted. */
  isGrounded: boolean;
}

function toCitation(dto: CitationDto): Citation {
  return {
    chunkId: dto.chunk_id,
    documentId: dto.document_id,
    documentName: dto.document_name,
    pageNumber: dto.page_number,
    excerpt: dto.excerpt,
  };
}

export async function askCourse(courseId: string, question: string): Promise<TutorAnswer> {
  const dto = await apiRequest<AskResponseDto>(`/v1/courses/${courseId}/ask`, {
    method: 'POST',
    body: { question },
  });

  return {
    answer: dto.answer,
    citations: dto.citations.map(toCitation),
    isGrounded: dto.is_grounded,
  };
}

export async function searchCourse(
  courseId: string,
  query: string,
  topK?: number,
): Promise<SearchResult[]> {
  const dto = await apiRequest<SearchResponseDto>(`/v1/courses/${courseId}/search`, {
    method: 'POST',
    body: topK === undefined ? { query } : { query, top_k: topK },
  });

  return dto.results.map((result) => ({
    chunkId: result.chunk_id,
    documentId: result.document_id,
    documentName: result.document_name,
    pageNumber: result.page_number,
    chunkIndex: result.chunk_index,
    content: result.content,
    similarity: result.similarity,
  }));
}
