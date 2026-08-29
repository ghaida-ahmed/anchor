import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '@/hooks/queries/queryKeys';
import * as coursesApi from '@/services/api/courses';
import type { CourseInput } from '@/services/api/courses';
import type { Course } from '@/types/domain';

export function useCourses() {
  return useQuery({
    queryKey: queryKeys.courses.all,
    queryFn: coursesApi.fetchCourses,
  });
}

export function useCourse(courseId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.courses.detail(courseId ?? ''),
    queryFn: () => coursesApi.fetchCourse(courseId as string),
    // 4xx responses are not retried — see the shared client's retry policy.
    enabled: Boolean(courseId),
  });
}

export function useCreateCourse() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: CourseInput) => coursesApi.createCourse(input),
    onSuccess: (course) => {
      // Seed the detail cache so opening the new course is instant.
      queryClient.setQueryData(queryKeys.courses.detail(course.id), course);
      void queryClient.invalidateQueries({ queryKey: queryKeys.courses.all });
    },
  });
}

export function useUpdateCourse(courseId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: Partial<CourseInput>) =>
      coursesApi.updateCourse(courseId, input),
    onSuccess: (course: Course) => {
      queryClient.setQueryData(queryKeys.courses.detail(course.id), course);
      void queryClient.invalidateQueries({ queryKey: queryKeys.courses.all });
    },
  });
}

export function useDeleteCourse() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (courseId: string) => coursesApi.deleteCourse(courseId),
    onSuccess: (_result, courseId) => {
      queryClient.removeQueries({ queryKey: queryKeys.courses.detail(courseId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.courses.all });
    },
  });
}
