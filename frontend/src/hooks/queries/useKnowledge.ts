import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '@/hooks/queries/queryKeys';
import * as knowledgeApi from '@/services/api/knowledge';
import * as studyGuideApi from '@/services/api/studyGuide';

export function useKnowledgeMap(courseId: string) {
  return useQuery({
    queryKey: queryKeys.knowledge.map(courseId),
    queryFn: () => knowledgeApi.fetchKnowledgeMap(courseId),
  });
}

/**
 * Generation is a mutation, not a query with a refetch: it costs one model call
 * per batch of topic pairs and must only ever happen because someone asked.
 */
export function useGenerateKnowledgeMap(courseId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => knowledgeApi.generateKnowledgeMap(courseId),
    onSuccess: (result) => {
      queryClient.setQueryData(queryKeys.knowledge.map(courseId), result);
      // New edges change what counts as a blocking gap.
      void queryClient.invalidateQueries({
        queryKey: queryKeys.knowledge.gaps(courseId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.studyGuide.forCourse(courseId),
      });
    },
  });
}

export function useKnowledgeGaps(courseId: string) {
  return useQuery({
    queryKey: queryKeys.knowledge.gaps(courseId),
    queryFn: () => knowledgeApi.fetchKnowledgeGaps(courseId),
  });
}

export function useStudyGuide(courseId: string) {
  return useQuery({
    queryKey: queryKeys.studyGuide.forCourse(courseId),
    queryFn: () => studyGuideApi.fetchStudyGuide(courseId),
  });
}

export function useGenerateStudyGuide(courseId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => studyGuideApi.generateStudyGuide(courseId),
    onSuccess: (guide) => {
      queryClient.setQueryData(queryKeys.studyGuide.forCourse(courseId), guide);
    },
  });
}
