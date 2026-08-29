import { QueryClient } from '@tanstack/react-query';

import { ApiError } from '@/services/api/client';

/**
 * Shared query client.
 *
 * Retrying a 4xx is pointless — a 401 or 404 will not become a 200 on a second
 * attempt, and retrying just delays the error the user needs to see.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
          return false;
        }
        return failureCount < 2;
      },
    },
    mutations: {
      retry: false,
    },
  },
});
