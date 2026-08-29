import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider } from 'react-router-dom';

import { AuthProvider } from '@/features/auth/AuthProvider';
import { router } from '@/routes/router';
import { queryClient } from '@/services/queryClient';

/**
 * Query client outermost: `AuthProvider` clears the cache on sign-out, so it has
 * to sit inside the provider that owns it.
 */
export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </QueryClientProvider>
  );
}
