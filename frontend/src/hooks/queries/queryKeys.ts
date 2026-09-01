/**
 * Every cache key in one place.
 *
 * Hierarchical so a mutation can invalidate a whole subtree — invalidating
 * `courses.all` also refreshes every individual course detail query.
 */
export const queryKeys = {
  courses: {
    all: ['courses'] as const,
    detail: (courseId: string) => ['courses', courseId] as const,
  },
  documents: {
    forCourse: (courseId: string) => ['courses', courseId, 'documents'] as const,
  },
  tutor: {
    forCourse: (courseId: string) => ['courses', courseId, 'tutor'] as const,
  },
  topics: {
    forCourse: (courseId: string) => ['courses', courseId, 'topics'] as const,
    syncStatus: (courseId: string) =>
      ['courses', courseId, 'topics', 'status'] as const,
  },
  quizzes: {
    forCourse: (courseId: string) => ['courses', courseId, 'quizzes'] as const,
    detail: (quizId: string) => ['quizzes', quizId] as const,
  },
  mastery: {
    forCourse: (courseId: string) => ['courses', courseId, 'mastery'] as const,
    recommendations: (courseId: string) =>
      ['courses', courseId, 'recommendations'] as const,
    attempts: (courseId: string) => ['courses', courseId, 'attempts'] as const,
  },
  flashcards: {
    forCourse: (courseId: string) => ['courses', courseId, 'flashcards'] as const,
    due: (courseId: string) => ['courses', courseId, 'flashcards', 'due'] as const,
  },
  knowledge: {
    map: (courseId: string) => ['courses', courseId, 'knowledge-map'] as const,
    gaps: (courseId: string) => ['courses', courseId, 'knowledge-gaps'] as const,
  },
  studyGuide: {
    forCourse: (courseId: string) => ['courses', courseId, 'study-guide'] as const,
  },
  retention: {
    history: (courseId: string) => ['courses', courseId, 'mastery', 'history'] as const,
    analytics: (courseId: string) => ['courses', courseId, 'analytics'] as const,
    exam: (courseId: string) => ['courses', courseId, 'exam'] as const,
  },
} as const;
