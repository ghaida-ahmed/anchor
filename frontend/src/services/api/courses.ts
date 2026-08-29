import { apiRequest } from '@/services/api/client';
import { toCourse, type CourseDto } from '@/services/api/dto';
import type { Course } from '@/types/domain';

export interface CourseInput {
  title: string;
  code: string;
  description: string;
}

export async function fetchCourses(): Promise<Course[]> {
  const dtos = await apiRequest<CourseDto[]>('/v1/courses');
  return dtos.map(toCourse);
}

export async function fetchCourse(courseId: string): Promise<Course> {
  return toCourse(await apiRequest<CourseDto>(`/v1/courses/${courseId}`));
}

export async function createCourse(input: CourseInput): Promise<Course> {
  return toCourse(
    await apiRequest<CourseDto>('/v1/courses', { method: 'POST', body: input }),
  );
}

export async function updateCourse(
  courseId: string,
  input: Partial<CourseInput>,
): Promise<Course> {
  return toCourse(
    await apiRequest<CourseDto>(`/v1/courses/${courseId}`, {
      method: 'PATCH',
      body: input,
    }),
  );
}

export function deleteCourse(courseId: string): Promise<void> {
  return apiRequest<void>(`/v1/courses/${courseId}`, { method: 'DELETE' });
}
