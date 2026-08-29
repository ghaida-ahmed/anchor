import { createBrowserRouter } from 'react-router-dom';

import { AppLayout } from '@/components/layout/AppLayout';
import { MarketingLayout } from '@/components/layout/MarketingLayout';
import { RedirectIfAuthenticated, RequireAuth } from '@/features/auth/RequireAuth';
import { CourseWorkspacePage } from '@/pages/CourseWorkspacePage';
import { CoursesPage } from '@/pages/CoursesPage';
import { DashboardPage } from '@/pages/DashboardPage';
import { LandingPage } from '@/pages/LandingPage';
import { LoginPage } from '@/pages/LoginPage';
import { NotFoundPage } from '@/pages/NotFoundPage';
import { RegisterPage } from '@/pages/RegisterPage';
import { paths } from '@/routes/paths';

/**
 * Three branches: the public marketing page, the auth pages (which bounce
 * signed-in users onward), and the product surface behind `RequireAuth`.
 */
export const router = createBrowserRouter([
  {
    element: <MarketingLayout />,
    children: [{ path: paths.landing, element: <LandingPage /> }],
  },
  {
    element: <RedirectIfAuthenticated />,
    children: [
      { path: paths.login, element: <LoginPage /> },
      { path: paths.register, element: <RegisterPage /> },
    ],
  },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppLayout />,
        children: [
          { path: paths.dashboard, element: <DashboardPage /> },
          { path: paths.courses, element: <CoursesPage /> },
          { path: '/courses/:courseId', element: <CourseWorkspacePage /> },
        ],
      },
    ],
  },
  { path: '*', element: <NotFoundPage /> },
]);
