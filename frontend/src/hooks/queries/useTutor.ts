import { useMutation } from '@tanstack/react-query';

import { askCourse } from '@/services/api/rag';

/**
 * Asking a question is a mutation, not a query: it is an explicit user action with
 * a side effect (a paid model call), and answers are not cached — the same question
 * asked again should hit the current state of the course's material.
 */
export function useAskTutor(courseId: string) {
  return useMutation({
    mutationFn: (question: string) => askCourse(courseId, question),
  });
}
