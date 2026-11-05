import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { type AuthContext, type Me, type Role, api } from '../api/client';

/**
 * Who is signed in. Sign-in is by mobile number and a one-time code (see SignInPage); the session is
 * an HttpOnly cookie, so identity only ever comes from GET /api/me.
 */
type Session = {
  me: Me;
  auth: AuthContext;
  switchTo: (role: Role) => Promise<void>;
  signOut: () => Promise<void>;
};
type State =
  | { status: 'loading' }
  | { status: 'signed_out'; refresh: () => Promise<void> }
  | ({ status: 'signed_in' } & Session);

const Context = createContext<State | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const [me, setMe] = useState<Me | null | undefined>(undefined);

  const refresh = useCallback(async () => {
    try {
      setMe(await api<Me>('/api/me'));
    } catch {
      setMe(null);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const value = useMemo<State>(() => {
    if (me === undefined) return { status: 'loading' };
    if (me === null) return { status: 'signed_out', refresh };
    return {
      status: 'signed_in',
      me,
      auth: {
        user_id: me.user_id,
        role: me.role,
        acting_for_patient_id: me.acting_for_patient_id,
      },
      switchTo: async (role: Role) => {
        await api('/api/auth/role', {
          method: 'POST',
          body: JSON.stringify({ role }),
        });
        queryClient.clear(); // never show one role's data to another
        await refresh();
      },
      signOut: async () => {
        await api('/api/auth/logout', { method: 'POST' });
        queryClient.clear();
        setMe(null);
      },
    };
  }, [me, refresh, queryClient]);

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useAuthState() {
  const value = useContext(Context);
  if (!value) throw new Error('AuthProvider missing');
  return value;
}

/** For pages behind sign-in: the session is guaranteed to exist. */
export function useAuth(): Session {
  const value = useAuthState();
  if (value.status !== 'signed_in') throw new Error('not signed in');
  return value;
}

export const useSession = useAuth;
