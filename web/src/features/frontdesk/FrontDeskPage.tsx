import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { useAuth } from '../../auth/AuthProvider';

type Handoff = { ticket_id: string; kind: string; status: string; reason: string };

export function FrontDeskPage() {
  const { auth } = useAuth();
  const { data = [], refetch } = useQuery({ queryKey: ['handoffs', auth.user_id], queryFn: () => api<Handoff[]>('/api/front-desk/handoffs', {}, auth), retry: false });
  async function close(id: string) { await api(`/api/front-desk/handoffs/${id}/status`, { method: 'POST', body: JSON.stringify({ status: 'closed' }) }, auth); await refetch(); }
  return <section><h2>Front desk</h2>{data.map((h) => <article key={h.ticket_id}><b>{h.kind}</b><p>{h.status} · {h.reason}</p><button onClick={() => close(h.ticket_id)}>Close</button></article>)}</section>;
}
