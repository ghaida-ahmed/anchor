import { apiRequest } from '@/services/api/client';
import { toUser, type TokenDto, type UserDto } from '@/services/api/dto';
import type { User } from '@/types/domain';

export interface Credentials {
  email: string;
  password: string;
}

export interface RegistrationDetails extends Credentials {
  name: string;
}

/** Registering also signs you in — the API returns a token directly. */
export function register(details: RegistrationDetails): Promise<TokenDto> {
  return apiRequest<TokenDto>('/v1/auth/register', {
    method: 'POST',
    body: details,
  });
}

export function login(credentials: Credentials): Promise<TokenDto> {
  return apiRequest<TokenDto>('/v1/auth/login', {
    method: 'POST',
    body: credentials,
  });
}

export async function fetchCurrentUser(): Promise<User> {
  return toUser(await apiRequest<UserDto>('/v1/auth/me'));
}

/**
 * Store the student's timezone.
 *
 * Sends an IANA identifier — what `Intl` already knows about the browser. It is a
 * timezone, not a location: it says when this person's day starts, not where they
 * are, and nothing is derived from an IP address.
 */
export async function updateTimezone(timezone: string): Promise<User> {
  return toUser(
    await apiRequest<UserDto>('/v1/auth/me/timezone', {
      method: 'PATCH',
      body: { timezone },
    }),
  );
}

/** What the browser reports, or UTC when it will not say. */
export function detectTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}
