import { useContext } from 'react';

import { AuthContext, type AuthContextValue } from '@/features/auth/AuthContext';

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (context === null) {
    throw new Error('useAuth must be used inside an <AuthProvider>.');
  }
  return context;
}
