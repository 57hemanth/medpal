export type Role =
  'patient' | 'caregiver' | 'doctor' | 'desk' | 'pharmacist' | 'compliance';

export type AuthContext = {
  user_id: string;
  role: Role;
  acting_for_patient_id: string | null;
};

/** The signed-in person, as GET /api/me returns them. */
export type Me = AuthContext & {
  name: string | null;
  phone: string | null;
  roles: Role[];
};

/**
 * Calls the API with the session cookie set at sign-in (HttpOnly: this code never sees it).
 * The `auth` argument is kept so callers state whose request it is; identity comes from the cookie.
 */
export async function api<T>(
  path: string,
  options: RequestInit = {},
  _auth?: AuthContext,
): Promise<T> {
  const headers = new Headers(options.headers);
  if (
    !(options.body instanceof FormData) &&
    options.body &&
    !headers.has('content-type')
  )
    headers.set('content-type', 'application/json');
  const response = await fetch(path, {
    ...options,
    headers,
    credentials: 'same-origin',
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}

/** A file the API serves (e.g. an uploaded record), with the same session. */
export async function apiFile(
  path: string,
  _auth?: AuthContext,
): Promise<Blob> {
  const response = await fetch(path, { credentials: 'same-origin' });
  if (!response.ok) throw new Error(await response.text());
  return response.blob();
}
