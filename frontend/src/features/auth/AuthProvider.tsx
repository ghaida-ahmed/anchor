import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';

import { AuthContext, type AuthStatus } from '@/features/auth/AuthContext';
import { clearToken, readToken, writeToken } from '@/lib/authStorage';
import * as authApi from '@/services/api/auth';
import { UNAUTHORIZED_EVENT } from '@/services/api/client';
import type { User } from '@/types/domain';

/**
 * Owns session state.
 *
 * On mount, any stored token is validated against `/auth/me` rather than trusted:
 * a token can be expired, revoked by a restart with a new signing key, or belong
 * to a user who no longer exists.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<AuthStatus>(() =>
    readToken() ? 'loading' : 'anonymous',
  );
  const [user, setUser] = useState<User | null>(null);

  const signOut = useCallback(() => {
    clearToken();
    setUser(null);
    setStatus('anonymous');
    // Never let one account's cached courses show up under the next sign-in.
    queryClient.clear();
  }, [queryClient]);

  useEffect(() => {
    if (!readToken()) return;

    let cancelled = false;
    authApi
      .fetchCurrentUser()
      .then((currentUser) => {
        if (cancelled) return;
        setUser(currentUser);
        setStatus('authenticated');
      })
      .catch(() => {
        if (cancelled) return;
        clearToken();
        setStatus('anonymous');
      });

    return () => {
      cancelled = true;
    };
  }, []);

  // The client dispatches this when the API rejects a token mid-session.
  useEffect(() => {
    const handle = () => signOut();
    window.addEventListener(UNAUTHORIZED_EVENT, handle);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, handle);
  }, [signOut]);

  const establishSession = useCallback(async (accessToken: string) => {
    writeToken(accessToken);
    const currentUser = await authApi.fetchCurrentUser();
    setUser(currentUser);
    setStatus('authenticated');
  }, []);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const { access_token } = await authApi.login({ email, password });
      await establishSession(access_token);
    },
    [establishSession],
  );

  const signUp = useCallback(
    async (name: string, email: string, password: string) => {
      const { access_token } = await authApi.register({ name, email, password });
      await establishSession(access_token);
    },
    [establishSession],
  );

  const value = useMemo(
    () => ({ status, user, signIn, signUp, signOut, setUser }),
    [status, user, signIn, signUp, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
