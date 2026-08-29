/**
 * Typed fetch wrapper for the ANCHOR API.
 *
 * Responsibilities kept here so no component ever calls `fetch` directly:
 * attaching the bearer token, unwrapping the backend's error envelope into a
 * message worth showing a user, and normalising transport failures.
 */

import { clearToken, readToken } from '@/lib/authStorage';

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api';

/** Fired when the API rejects our token, so the auth layer can sign the user out. */
export const UNAUTHORIZED_EVENT = 'anchor:unauthorized';

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }

  /** True when the request never reached the server. */
  get isNetworkError(): boolean {
    return this.status === 0;
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  /** Serialised as JSON. Mutually exclusive with `formData`. */
  body?: unknown;
  formData?: FormData;
  signal?: AbortSignal;
}

const FALLBACK_MESSAGES: Record<number, string> = {
  400: 'That request could not be processed.',
  401: 'Your session has expired. Please sign in again.',
  403: 'You do not have access to that.',
  404: 'That item could not be found.',
  409: 'That conflicts with something that already exists.',
  413: 'That file is too large.',
  422: 'Some of those details were not valid.',
  500: 'Something went wrong on our side. Please try again.',
  501: 'That feature is not available yet.',
};

/**
 * Pull a human-readable message out of the response.
 *
 * The API answers with `{"detail": "..."}`. FastAPI's own validation errors use
 * `{"detail": [{loc, msg, ...}]}`, so both shapes are handled — a raw array would
 * otherwise render as "[object Object]".
 */
async function extractMessage(response: Response): Promise<string> {
  const fallback =
    FALLBACK_MESSAGES[response.status] ?? 'Something went wrong. Please try again.';

  try {
    const payload: unknown = await response.json();
    if (typeof payload !== 'object' || payload === null) return fallback;

    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === 'string' && detail.trim()) return detail;

    if (Array.isArray(detail)) {
      const first = detail[0] as { msg?: unknown } | undefined;
      if (first && typeof first.msg === 'string') {
        // Pydantic prefixes messages with "Value error, "; drop the noise.
        return first.msg.replace(/^Value error,\s*/, '');
      }
    }
    return fallback;
  } catch {
    return fallback;
  }
}

export async function apiRequest<TResponse>(
  path: string,
  options: RequestOptions = {},
): Promise<TResponse> {
  const { method = 'GET', body, formData, signal } = options;

  const headers: Record<string, string> = { Accept: 'application/json' };
  const token = readToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  // FormData sets its own multipart boundary — never set Content-Type for it.
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  // Optional keys are omitted rather than set to undefined: `exactOptionalPropertyTypes`
  // treats an explicit undefined as a type error against `RequestInit`.
  const init: RequestInit = { method, headers };
  const payload = formData ?? (body === undefined ? null : JSON.stringify(body));
  if (payload !== null) init.body = payload;
  if (signal) init.signal = signal;

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, init);
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError('Could not reach the ANCHOR API. Is the backend running?', 0);
  }

  if (response.status === 401 && token) {
    // The token we sent was rejected: drop it and let the app react.
    clearToken();
    window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
  }

  if (!response.ok) {
    throw new ApiError(await extractMessage(response), response.status);
  }

  // 204 No Content has no body to parse.
  if (response.status === 204) return undefined as TResponse;

  return (await response.json()) as TResponse;
}

/**
 * Fetch a binary response (a stored document) with the bearer token attached.
 *
 * Separate from `apiRequest` because that one always parses JSON, and because the
 * error envelope for a failed download is still JSON while a success is not.
 */
export async function apiRequestBlob(path: string): Promise<Blob> {
  const headers: Record<string, string> = {};
  const token = readToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, { headers });
  } catch {
    throw new ApiError('Could not reach the ANCHOR API. Is the backend running?', 0);
  }

  if (response.status === 401 && token) {
    clearToken();
    window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
  }

  if (!response.ok) {
    throw new ApiError(await extractMessage(response), response.status);
  }

  return response.blob();
}

/** Turns any thrown value into something safe to render. */
export function toErrorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return 'Something went wrong. Please try again.';
}
