import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { useAuth } from '../../auth/AuthProvider';

type Consent = { consent_id: string; grantee_user_id: string; scope: string[]; purpose: string; revoked_at: string | null };

export function ConsentPage() {
  const { auth } = useAuth();
  const { data = [], refetch } = useQuery({ queryKey: ['consents', auth.user_id], queryFn: () => api<Consent[]>('/api/consents', {}, auth) });
  async function revoke(id: string) { await api(`/api/consents/${id}/revoke`, { method: 'POST' }, auth); await refetch(); }
  return <section><h2>Consent</h2>{data.map((c) => <article key={c.consent_id}><b>{c.grantee_user_id}</b><p>{c.scope.join(', ')} · {c.purpose}</p>{c.revoked_at ? <em>revoked</em> : <button onClick={() => revoke(c.consent_id)}>Revoke</button>}</article>)}</section>;
}
