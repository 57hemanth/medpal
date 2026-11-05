import { createContext, useContext, useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { AuthContext, Role, devIdentity } from '../api/client';

type AuthState = { auth: AuthContext | null; setRole: (role: Role) => void; logout: () => void };
const Context = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [role, setRole] = useState<Role | null>(null);
  const queryClient = useQueryClient();
  const value = useMemo(() => ({
    auth: role ? devIdentity(role) : null,
    setRole: (next: Role) => { queryClient.clear(); setRole(next); },
    logout: () => { queryClient.clear(); setRole(null); },
  }), [role, queryClient]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useSession() {
  const value = useContext(Context);
  if (!value) throw new Error('AuthProvider missing');
  return value;
}

export function useAuth() {
  const value = useSession();
  if (!value.auth) throw new Error('Select a test login first');
  return { ...value, auth: value.auth };
}
