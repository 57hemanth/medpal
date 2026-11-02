import { useState } from 'react';
import { api } from '../../api/client';
import { useAuth } from '../../auth/AuthProvider';

type Candidate = { slot_id: string; doctor_name: string; clinic_name: string; display_time: string };
type TriageOut = { thread_id: string; status: string; reply?: string; candidates?: Candidate[]; booking_id?: string };

export function TriagePage() {
  const { auth } = useAuth();
  const [text, setText] = useState('knee pain for a week');
  const [result, setResult] = useState<TriageOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function start() { setError(null); setResult(await api<TriageOut>('/triage', { method: 'POST', body: JSON.stringify({ text }) }, auth).catch((e) => { setError(String(e)); return null; })); }
  async function book(slot_id: string) { if (!result) return; setResult(await api<TriageOut>(`/triage/${result.thread_id}/resume`, { method: 'POST', body: JSON.stringify({ slot_id, idempotency_key: crypto.randomUUID() }) }, auth)); }
  return <section><h2>Patient triage</h2><textarea value={text} onChange={(e) => setText(e.target.value)} /><button onClick={start}>Find care</button>{error && <p role="alert">{error}</p>}{result?.reply && <p>{result.reply}</p>}{result?.candidates?.map((c) => <button key={c.slot_id} onClick={() => book(c.slot_id)}>{c.doctor_name} · {c.clinic_name} · {c.display_time}</button>)}{result?.booking_id && <strong>Booked: {result.booking_id}</strong>}</section>;
}
