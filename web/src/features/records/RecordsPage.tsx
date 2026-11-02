import { FormEvent, useState } from 'react';
import { api } from '../../api/client';
import { useAuth } from '../../auth/AuthProvider';

type Answer = { status: string; answer: string; citations: { chunk_id: string; doc_id: string; page: number; text: string }[] };

export function RecordsPage() {
  const { auth } = useAuth();
  const [question, setQuestion] = useState('LDL');
  const [answer, setAnswer] = useState<Answer | null>(null);
  async function ask() { setAnswer(await api<Answer>('/api/records/questions', { method: 'POST', body: JSON.stringify({ question }) }, auth)); }
  async function upload(e: FormEvent<HTMLFormElement>) { e.preventDefault(); const data = new FormData(e.currentTarget); data.set('patient_id', auth.acting_for_patient_id ?? ''); await api('/api/records', { method: 'POST', body: data }, auth); }
  return <section><h2>Records Q&A</h2><form onSubmit={upload}><input type="file" name="file" /><button>Upload</button></form><input value={question} onChange={(e) => setQuestion(e.target.value)} /><button onClick={ask}>Ask</button>{answer && <article><h3>{answer.status}</h3><p>{answer.answer}</p>{answer.citations.map((c) => <blockquote key={c.chunk_id}>p{c.page}: {c.text}</blockquote>)}</article>}</section>;
}
