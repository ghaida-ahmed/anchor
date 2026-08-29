/**
 * Access-token persistence.
 *
 * The token is kept in `localStorage`. The tradeoff, documented in the README:
 * localStorage is readable by any script on the origin, so a successful XSS can
 * steal a session. An httpOnly cookie would not be script-readable, but the SPA
 * and API are separate origins in development, which pulls in CSRF protection and
 * cookie/CORS configuration for little gain on a portfolio project. Tokens are
 * short-lived and carry no data beyond the user id and expiry.
 *
 * Reads are defensive: private-browsing modes can make localStorage throw.
 */

const TOKEN_KEY = 'anchor.access_token';

export function readToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function writeToken(token: string): void {
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
  } catch {
    // Session simply will not survive a reload — not worth failing the login for.
  }
}

export function clearToken(): void {
  try {
    window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Nothing useful to do.
  }
}
