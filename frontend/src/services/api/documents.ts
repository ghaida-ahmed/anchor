import { apiRequest, apiRequestBlob } from '@/services/api/client';
import { toDocument, type DocumentDto } from '@/services/api/dto';
import type { CourseDocument } from '@/types/domain';

export async function fetchCourseDocuments(courseId: string): Promise<CourseDocument[]> {
  const dtos = await apiRequest<DocumentDto[]>(`/v1/courses/${courseId}/documents`);
  return dtos.map(toDocument);
}

export async function uploadDocument(
  courseId: string,
  file: File,
): Promise<CourseDocument> {
  const formData = new FormData();
  formData.append('file', file);

  return toDocument(
    await apiRequest<DocumentDto>(`/v1/courses/${courseId}/documents`, {
      method: 'POST',
      formData,
    }),
  );
}

export function deleteDocument(documentId: string): Promise<void> {
  return apiRequest<void>(`/v1/documents/${documentId}`, { method: 'DELETE' });
}

/** Rebuild a document's chunks — used to retry a failed document. */
export async function reprocessDocument(documentId: string): Promise<CourseDocument> {
  return toDocument(
    await apiRequest<DocumentDto>(`/v1/documents/${documentId}/reprocess`, {
      method: 'POST',
    }),
  );
}


/**
 * Fetch a document's original file as a blob.
 *
 * A plain `<a href>` cannot carry the Authorization header, so the file is fetched
 * with the token and handed to the browser as an object URL. Callers must revoke
 * that URL when finished.
 */
export async function fetchDocumentBlobUrl(documentId: string): Promise<string> {
  const blob = await apiRequestBlob(`/v1/documents/${documentId}/download`);
  return URL.createObjectURL(blob);
}
