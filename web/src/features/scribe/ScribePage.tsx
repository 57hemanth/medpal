import { useState } from 'react';
import { api } from '../../api/client';
import { useAuth } from '../../auth/AuthProvider';

type Draft = { subjective: string; objective: string; assessment: string; plan: string; medicines: string[] };

export function ScribePage() {
  const { auth } = useAuth();
  const [transcript, setTranscript] = useState('Doctor said continue paracetamol if fever returns.');
  const [draft, setDraft] = useState<Draft | null>(null);
  async function generate() { setDraft(await api<Draft>('/api/scribe/draft', { method: 'POST', body: JSON.stringify({ transcript }) }, auth)); }
  return <section><h2>Scribe review</h2><textarea value={transcript} onChange={(e) => setTranscript(e.target.value)} /><button onClick={generate}>Draft SOAP</button>{draft && <pre>{JSON.stringify(draft, null, 2)}</pre>}</section>;
}
