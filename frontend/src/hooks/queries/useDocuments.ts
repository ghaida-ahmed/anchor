import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '@/hooks/queries/queryKeys';
import * as documentsApi from '@/services/api/documents';

/** How often to re-check while a document is still being processed. */
const PROCESSING_POLL_MS = 2_000;

export function useCourseDocuments(courseId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.documents.forCourse(courseId ?? ''),
    queryFn: () => documentsApi.fetchCourseDocuments(courseId as string),
    enabled: Boolean(courseId),
    // Processing happens in a background task with no push channel, so the list
    // polls — but only while something is actually pending. Once every document
    // is ready or failed, `false` stops the timer.
    refetchInterval: (query) => {
      const documents = query.state.data;
      if (!documents) return false;

      const pending = documents.some(
        (document) =>
          document.processingStatus === 'uploaded' ||
          document.processingStatus === 'processing',
      );
      return pending ? PROCESSING_POLL_MS : false;
    },
  });
}

export function useUploadDocument(courseId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (file: File) => documentsApi.uploadDocument(courseId, file),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.documents.forCourse(courseId),
      });
      // The document count on the course card and header changes too.
      void queryClient.invalidateQueries({ queryKey: queryKeys.courses.all });
    },
  });
}

export function useReprocessDocument(courseId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (documentId: string) => documentsApi.reprocessDocument(documentId),
    onSuccess: () => {
      // The document goes back to a pending state, which restarts polling.
      void queryClient.invalidateQueries({
        queryKey: queryKeys.documents.forCourse(courseId),
      });
    },
  });
}

export function useDeleteDocument(courseId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (documentId: string) => documentsApi.deleteDocument(documentId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.documents.forCourse(courseId),
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.courses.all });
    },
  });
}
