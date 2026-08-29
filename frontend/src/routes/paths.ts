/** Single source of truth for route paths — never hard-code a URL in a component. */
export const paths = {
  landing: '/',
  login: '/login',
  register: '/register',
  dashboard: '/dashboard',
  courses: '/courses',
  course: (courseId: string) => `/courses/${courseId}`,
} as const;
