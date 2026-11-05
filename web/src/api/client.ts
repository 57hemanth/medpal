export type Role =
  'patient' | 'caregiver' | 'doctor' | 'desk' | 'pharmacist' | 'compliance';

export type AuthContext = {
  user_id: string;
  role: Role;
  acting_for_patient_id: string | null;
};

const DEV_USERS: Record<Role, AuthContext> = {
  patient: {
    user_id: '00000000-0000-0000-0000-0000000e0001',
    role: 'patient',
    acting_for_patient_id: '00000000-0000-0000-0000-0000000b0001',
  },
  caregiver: {
    user_id: '00000000-0000-0000-0000-0000000e0001',
    role: 'caregiver',
    acting_for_patient_id: null,
  },
  doctor: {
    user_id: '00000000-0000-0000-0000-0000000e0004',
    role: 'doctor',
    acting_for_patient_id: null,
  },
  desk: {
    user_id: '00000000-0000-0000-0000-0000000e0003',
    role: 'desk',
    acting_for_patient_id: null,
  },
  pharmacist: {
    user_id: '00000000-0000-0000-0000-0000000e0005',
    role: 'pharmacist',
    acting_for_patient_id: null,
  },
  compliance: {
    user_id: '00000000-0000-0000-0000-0000000e0006',
    role: 'compliance',
    acting_for_patient_id: null,
  },
};

export const devIdentity = (role: Role) => DEV_USERS[role];

export async function api<T>(
  path: string,
  options: RequestInit = {},
  auth: AuthContext = DEV_USERS.patient,
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set('X-Dev-User-Id', auth.user_id);
  headers.set('X-Dev-Role', auth.role);
  if (auth.acting_for_patient_id)
    headers.set('X-Dev-Patient-Id', auth.acting_for_patient_id);
  if (
    !(options.body instanceof FormData) &&
    options.body &&
    !headers.has('content-type')
  )
    headers.set('content-type', 'application/json');
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}

/** A file the API serves (e.g. an uploaded record), fetched with the same identity headers as api(). */
export async function apiFile(path: string, auth: AuthContext): Promise<Blob> {
  const headers = new Headers();
  headers.set('X-Dev-User-Id', auth.user_id);
  headers.set('X-Dev-Role', auth.role);
  if (auth.acting_for_patient_id)
    headers.set('X-Dev-Patient-Id', auth.acting_for_patient_id);
  const response = await fetch(path, { headers });
  if (!response.ok) throw new Error(await response.text());
  return response.blob();
}
