import { apiRequest } from '@/services/api/client';

export interface HealthResponse {
  status: string;
  service: string;
}

/** Unauthenticated liveness probe, used by the sidebar indicator. */
export function fetchHealth(): Promise<HealthResponse> {
  return apiRequest<HealthResponse>('/health');
}
