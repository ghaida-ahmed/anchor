import { Navigate, Outlet, useLocation } from 'react-router-dom';

import { FullPageSpinner } from '@/components/ui/Spinner';
import { useAuth } from '@/features/auth/useAuth';
import { paths } from '@/routes/paths';

/**
 * Gate for the product routes.
 *
 * While the stored token is being validated it renders a spinner rather than
 * redirecting — otherwise a refresh would bounce a signed-in user to the login
 * page for a frame. The attempted location is passed along so login can return
 * the user where they were headed.
 */
export function RequireAuth() {
  const { status } = useAuth();
  const location = useLocation();

  if (status === 'loading') return <FullPageSpinner label="Restoring your session…" />;

  if (status === 'anonymous') {
    return <Navigate to={paths.login} state={{ from: location.pathname }} replace />;
  }

  return <Outlet />;
}

/** Inverse guard: keeps signed-in users off the login and register pages. */
export function RedirectIfAuthenticated() {
  const { status } = useAuth();

  if (status === 'loading') return <FullPageSpinner label="Checking your session…" />;
  if (status === 'authenticated') return <Navigate to={paths.dashboard} replace />;

  return <Outlet />;
}
