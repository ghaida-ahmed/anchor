import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '@/hooks/queries/queryKeys';
import * as retentionApi from '@/services/api/retention';
import type { ReviewRating } from '@/services/api/retention';

/**
 * None of these queries cost anything: mastery, analytics, the due queue and exam
 * readiness are all database reads on the backend. They are safe to refetch.
 */

export function useMastery(courseId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.mastery.forCourse(courseId ?? ''),
    queryFn: () => retentionApi.fetchMastery(courseId as string),
    enabled: Boolean(courseId),
  });
}

export function useAnalytics(courseId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.retention.analytics(courseId ?? ''),
    queryFn: () => retentionApi.fetchAnalytics(courseId as string),
    enabled: Boolean(courseId),
  });
}

export function useDueSummary(courseId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.flashcards.due(courseId ?? ''),
    queryFn: () => retentionApi.fetchDueSummary(courseId as string),
    enabled: Boolean(courseId),
  });
}

export function useSubmitReview(courseId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: { flashcardId: string; rating: ReviewRating }) =>
      retentionApi.submitReview(input.flashcardId, input.rating),
    onSuccess: () => {
      // A review changes the due queue, the mastery estimate and the trend.
      void queryClient.invalidateQueries({
        queryKey: queryKeys.flashcards.due(courseId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.mastery.forCourse(courseId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.mastery.recommendations(courseId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.retention.analytics(courseId),
      });
    },
  });
}

export function useExamStatus(courseId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.retention.exam(courseId ?? ''),
    queryFn: () => retentionApi.fetchExamStatus(courseId as string),
    enabled: Boolean(courseId),
  });
}

export function useSetExamDate(courseId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (examDate: string | null) =>
      retentionApi.setExamDate(courseId, examDate),
    onSuccess: (status) => {
      queryClient.setQueryData(queryKeys.retention.exam(courseId), status);
    },
  });
}
