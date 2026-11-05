import { createContext, useContext, useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { type AuthContext, type Role, devIdentity } from '../api/client';

/**
 * The active workspace profile. Sign-in is not built yet: the app opens on the last profile used
 * (or the patient profile) and the sidebar switches between seeded synthetic identities.
 */
type Session = { auth: AuthContext; switchTo: (role: Role) => void };
const Context = createContext<Session | null>(null);
const KEY = 'medpal.profile';
const ROLES: Role[] = [
  'patient',
  'caregiver',
  'doctor',
  'desk',
  'pharmacist',
  'compliance',
];

function initialRole(): Role {
  try {
    const saved = window.localStorage.getItem(KEY) as Role | null;
    return saved && ROLES.includes(saved) ? saved : 'patient';
  } catch {
    return 'patient';
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [role, setRole] = useState<Role>(initialRole);
  const queryClient = useQueryClient();
  const value = useMemo(
    () => ({
      auth: devIdentity(role),
      switchTo: (next: Role) => {
        queryClient.clear(); // never show one profile's data to another
        try {
          window.localStorage.setItem(KEY, next);
        } catch {
          /* private mode: the choice just isn't remembered */
        }
        setRole(next);
      },
    }),
    [role, queryClient],
  );
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useSession() {
  const value = useContext(Context);
  if (!value) throw new Error('AuthProvider missing');
  return value;
}

export function useAuth() {
  return useSession();
}
