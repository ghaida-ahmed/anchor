import { useEffect, useState } from 'react';

import { fetchHealth } from '@/services/api/health';

export type ApiStatus = 'checking' | 'online' | 'unreachable';

/**
 * Polls the backend once on mount. Used by the sidebar indicator so it is obvious
 * whether the API is reachable before the student wonders why nothing loads.
 */
export function useApiHealth(): ApiStatus {
  const [status, setStatus] = useState<ApiStatus>('checking');

  useEffect(() => {
    let cancelled = false;

    fetchHealth()
      .then(() => {
        if (!cancelled) setStatus('online');
      })
      .catch(() => {
        if (!cancelled) setStatus('unreachable');
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return status;
}
