import { createContext, useContext, useMemo, useState } from 'react';
import { AuthContext, Role, devIdentity } from '../api/client';

type AuthState = { auth: AuthContext; setRole: (role: Role) => void };
const Context = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [role, setRole] = useState<Role>('patient');
  const value = useMemo(() => ({ auth: devIdentity(role), setRole }), [role]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useAuth() {
  const value = useContext(Context);
  if (!value) throw new Error('AuthProvider missing');
  return value;
}
