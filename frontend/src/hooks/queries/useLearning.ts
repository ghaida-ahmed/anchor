import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '@/hooks/queries/queryKeys';
import * as learningApi from '@/services/api/learning';
import type {
  GenerateFlashcardsInput,
  GenerateQuizInput,
} from '@/services/api/learning';

/* --- Topics --------------------------------------------------------------- */

export function useTopics(courseId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.topics.forCourse(courseId ?? ''),
    queryFn: () => learningApi.fetchTopics(courseId as string),
    enabled: Boolean(courseId),
  });
}

/**
 * Whether topics reflect the course's processed material.
 *
 * Polled while documents are still processing, because topics are extracted
 * automatically once a document reaches `ready` and the banner should clear
 * itself without a manual refresh.
 */
export function useTopicSyncStatus(courseId: string | undefined, poll = false) {
  return useQuery({
    queryKey: queryKeys.topics.syncStatus(courseId ?? ''),
    queryFn: () => learningApi.fetchTopicSyncStatus(courseId as string),
    enabled: Boolean(courseId),
    refetchInterval: poll ? 4000 : false,
  });
}

export function useExtractTopics(courseId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => learningApi.extractTopics(courseId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.topics.forCourse(courseId),
      });
      // Deactivating a topic changes what mastery reports.
      void queryClient.invalidateQueries({
        queryKey: queryKeys.mastery.forCourse(courseId),
      });
    },
  });
}

/* --- Quizzes -------------------------------------------------------------- */

export function useQuizzes(courseId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.quizzes.forCourse(courseId ?? ''),
    queryFn: () => learningApi.fetchQuizzes(courseId as string),
    enabled: Boolean(courseId),
  });
}

/**
 * Generating a quiz is a mutation, not a query: it costs a model call, so it must
 * never fire on render or refetch. The result is persisted server-side, so a page
 * reload re-reads rather than regenerating.
 */
export function useGenerateQuiz(courseId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: GenerateQuizInput) => learningApi.generateQuiz(courseId, input),
    onSuccess: (quiz) => {
      queryClient.setQueryData(queryKeys.quizzes.detail(quiz.id), quiz);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.quizzes.forCourse(courseId),
      });
    },
  });
}

export function useStartAttempt() {
  return useMutation({
    mutationFn: (quizId: string) => learningApi.startAttempt(quizId),
  });
}

export function useSubmitAnswer() {
  return useMutation({
    mutationFn: (input: {
      attemptId: string;
      questionId: string;
      selectedIndex: number;
      answeredInSeconds?: number;
    }) =>
      learningApi.submitAnswer(
        input.attemptId,
        input.questionId,
        input.selectedIndex,
        input.answeredInSeconds,
      ),
  });
}

/**
 * Marking runs on the server while this is in flight, so it is noticeably slower
 * than `useSubmitAnswer`. The runner says so rather than showing a bare spinner.
 */
export function useSubmitShortAnswer() {
  return useMutation({
    mutationFn: (input: {
      attemptId: string;
      questionId: string;
      responseText: string;
      answeredInSeconds?: number;
    }) =>
      learningApi.submitShortAnswer(
        input.attemptId,
        input.questionId,
        input.responseText,
        input.answeredInSeconds,
      ),
  });
}

export function useCompleteAttempt(courseId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (attemptId: string) => learningApi.completeAttempt(attemptId),
    onSuccess: () => {
      // Mastery moved, so every derived view is stale.
      void queryClient.invalidateQueries({
        queryKey: queryKeys.mastery.forCourse(courseId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.mastery.recommendations(courseId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.mastery.attempts(courseId),
      });
    },
  });
}

/* --- Mastery -------------------------------------------------------------- */

// `useMastery` now lives in useRetention.ts: mastery gained a time dimension in
// Phase 5, and the richer shape belongs with the rest of the retention layer.

export function useRecommendations(courseId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.mastery.recommendations(courseId ?? ''),
    queryFn: () => learningApi.fetchRecommendations(courseId as string),
    enabled: Boolean(courseId),
  });
}

export function useAttempts(courseId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.mastery.attempts(courseId ?? ''),
    queryFn: () => learningApi.fetchAttempts(courseId as string),
    enabled: Boolean(courseId),
  });
}

/* --- Flashcards ----------------------------------------------------------- */

export function useFlashcards(courseId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.flashcards.forCourse(courseId ?? ''),
    queryFn: () => learningApi.fetchFlashcards(courseId as string),
    enabled: Boolean(courseId),
  });
}

export function useGenerateFlashcards(courseId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: GenerateFlashcardsInput) =>
      learningApi.generateFlashcards(courseId, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.flashcards.forCourse(courseId),
      });
    },
  });
}
