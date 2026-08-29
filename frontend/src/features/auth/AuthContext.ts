import { createContext } from 'react';

import type { User } from '@/types/domain';

/**
 * `loading` covers the first-paint token check, so guards can wait instead of
 * bouncing a signed-in user to the login page on refresh.
 */
export type AuthStatus = 'loading' | 'authenticated' | 'anonymous';

export interface AuthContextValue {
  status: AuthStatus;
  user: User | null;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (name: string, email: string, password: string) => Promise<void>;
  signOut: () => void;
  /** Replace the cached user after a profile change, e.g. the timezone. */
  setUser: (user: User) => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);
