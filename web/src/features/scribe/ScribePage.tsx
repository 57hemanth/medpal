import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AudioLines,
  CalendarDays,
  FilePenLine,
  HeartPulse,
  Mic,
  NotebookPen,
  PenLine,
  RotateCcw,
  ShieldCheck,
  Stethoscope,
  WandSparkles,
} from 'lucide-react';
import { api } from '../../api/client';
import { useAuth } from '../../auth/AuthProvider';
import {
  Badge,
  Button,
  EmptyState,
  ErrorNotice,
  PageHeader,
  PrivacyNote,
  formatDate,
  humanError,
} from '../../components/ui';

const FIELDS = ['subjective', 'objective', 'assessment', 'plan'] as const;
type Field = (typeof FIELDS)[number];
type Soap = Record<Field, string> & { medicines: string[] };

interface Consultation {
  appt_id: string;
  starts_at: string;
  clinic_name: string;
  patient_name: string | null;
  encounter_id: string | null;
  signed: boolean;
}
interface StockFlag {
  medicine: string;
  status: 'in_stock' | 'out_of_stock' | 'stale' | 'not_in_formulary';
  qty: number | null;
  as_of: string | null;
}
interface Session {
  thread_id: string;
  status: 'awaiting_review' | 'signed';
  soap: Soap | null;
  medicines: string[];
  stock_flags: StockFlag[];
  rejected_medicines: string[];
  drafting_unavailable: boolean;
  signed: { note_id: string; version: number; content_hash: string } | null;
}

const STOCK_LABEL: Record<
  StockFlag['status'],
  {
    tone: 'green' | 'red' | 'amber' | 'neutral';
    text: (f: StockFlag) => string;
  }
> = {
  in_stock: { tone: 'green', text: (f) => `In stock · ${f.qty}` },
  out_of_stock: { tone: 'red', text: () => 'Out of stock' },
  stale: {
    tone: 'amber',
    text: (f) =>
      f.as_of ? `Stock as of ${formatDate(f.as_of)}` : 'Stock unknown',
  },
  not_in_formulary: { tone: 'neutral', text: () => 'Not in formulary' },
};

export function ScribePage() {
  const { auth } = useAuth();
  const client = useQueryClient();
  const [consultation, setConsultation] = useState<Consultation | null>(null);
  const [encounterId, setEncounterId] = useState<string | null>(null);
  const [transcript, setTranscript] = useState('');
  const [session, setSession] = useState<Session | null>(null);
  const [soap, setSoap] = useState<Soap | null>(null);
  const [comments, setComments] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState<
    'start' | 'draft' | 'audio' | 'edit' | 'reject' | 'sign' | null
  >(null);
  const { data: consultations = [], error: listError } = useQuery({
    queryKey: ['consultations', auth.user_id],
    queryFn: () => api<Consultation[]>('/api/scribe/consultations', {}, auth),
    retry: false,
  });

  function reset() {
    setSession(null);
    setSoap(null);
    setComments('');
  }

  async function choose(item: Consultation) {
    if (busy) return;
    setBusy('start');
    setError('');
    reset();
    try {
      const { encounter_id } = await api<{ encounter_id: string }>(
        '/api/scribe/encounters',
        { method: 'POST', body: JSON.stringify({ appt_id: item.appt_id }) },
        auth,
      );
      setConsultation(item);
      setEncounterId(encounter_id);
    } catch (cause) {
      setError(humanError(cause));
    } finally {
      setBusy(null);
    }
  }

  function show(next: Session) {
    setSession(next);
    setSoap(next.soap);
    if (next.status === 'signed')
      void client.invalidateQueries({
        queryKey: ['consultations', auth.user_id],
      });
  }

  async function generate() {
    if (busy || !encounterId || transcript.trim().length < 10) return;
    setBusy('draft');
    setError('');
    reset();
    try {
      show(
        await api<Session>(
          '/api/scribe/sessions',
          {
            method: 'POST',
            body: JSON.stringify({ encounter_id: encounterId, transcript }),
          },
          auth,
        ),
      );
    } catch (cause) {
      setError(humanError(cause));
    } finally {
      setBusy(null);
    }
  }

  async function decide(action: 'edit' | 'reject' | 'sign') {
    if (busy || !session || !soap) return;
    setBusy(action);
    setError('');
    try {
      const body =
        action === 'reject' ? { action, comments } : { action, soap };
      show(
        await api<Session>(
          `/api/scribe/sessions/${session.thread_id}/resume`,
          { method: 'POST', body: JSON.stringify(body) },
          auth,
        ),
      );
      if (action === 'reject') setComments('');
    } catch (cause) {
      setError(humanError(cause));
    } finally {
      setBusy(null);
    }
  }

  async function transcribe(file: File) {
    setBusy('audio');
    setError('');
    try {
      const result = await api<{ transcript: string }>(
        '/api/scribe/transcribe',
        {
          method: 'POST',
          body: file,
          headers: { 'content-type': 'audio/wav' },
        },
        auth,
      );
      setTranscript(result.transcript);
      reset();
    } catch (cause) {
      setError(humanError(cause));
    } finally {
      setBusy(null);
    }
  }

  const reviewing = session?.status === 'awaiting_review' && soap;
  return (
    <section>
      <PageHeader
        eyebrow="Clinical"
        title="Consultations"
        description="Start a consultation, review the drafted SOAP note with stock-checked prescriptions, then sign. Nothing is saved to the record until you sign."
        action={<Badge tone="amber">Doctor sign-off required</Badge>}
      />
      <div className="mb-6">
        <ErrorNotice
          message={error || (listError ? humanError(listError) : '')}
        />
      </div>

      <div className="panel mb-6 overflow-hidden">
        <div className="flex items-center gap-3 border-b border-line px-6 py-5">
          <Stethoscope size={18} className="text-brand-600" />
          <h2 className="text-sm font-semibold">Your consultations</h2>
          <span className="ml-auto text-[11px] text-muted">Step 1</span>
        </div>
        {consultations.length === 0 ? (
          <p className="p-6 text-xs text-muted">
            No booked consultations with you yet.
          </p>
        ) : (
          <ul className="divide-y divide-line">
            {consultations.every((item) => item.signed) && (
              <li className="px-6 py-3 text-xs text-muted">
                Every consultation here is already signed. New ones appear as
                patients book with you; signed notes can't be drafted again.
              </li>
            )}
            {consultations.map((item) => (
              <li
                key={item.appt_id}
                className="flex flex-wrap items-center gap-3 px-6 py-3"
              >
                <CalendarDays size={14} className="text-brand-600" />
                <span className="text-sm font-medium">
                  {item.patient_name ?? 'Patient'}
                </span>
                <span className="text-xs text-muted">
                  {formatDate(item.starts_at)} · {item.clinic_name}
                </span>
                {item.signed ? (
                  <Badge tone="green">Signed</Badge>
                ) : (
                  <Button
                    variant="secondary"
                    className="ml-auto px-3 text-xs"
                    busy={
                      busy === 'start' && consultation?.appt_id === item.appt_id
                    }
                    disabled={!!busy}
                    aria-pressed={consultation?.appt_id === item.appt_id}
                    onClick={() => void choose(item)}
                  >
                    {consultation?.appt_id === item.appt_id
                      ? 'Selected'
                      : 'Start consultation'}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="grid items-start gap-6 xl:grid-cols-2">
        <div className="panel overflow-hidden">
          <div className="flex items-center gap-3 border-b border-line px-6 py-5">
            <NotebookPen size={18} className="text-brand-600" />
            <h2 className="text-sm font-semibold">Consultation transcript</h2>
            <span className="ml-auto text-[11px] text-muted">Step 2</span>
          </div>
          <div className="p-6">
            <label className="flex cursor-pointer items-center gap-4 rounded-xl border border-dashed border-brand-200 bg-brand-50/40 p-4 focus-within:ring-2 focus-within:ring-brand-600 hover:bg-brand-50">
              <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-white text-brand-600">
                <Mic size={20} />
              </span>
              <span>
                <span className="block text-xs font-semibold">
                  {busy === 'audio'
                    ? 'Transcribing locally…'
                    : 'Add consultation audio'}
                </span>
                <span className="mt-1 block text-[11px] text-muted">
                  PCM WAV · up to 16 MB / 30 min
                </span>
              </span>
              <input
                type="file"
                className="sr-only"
                accept=".wav,audio/wav"
                disabled={!!busy}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void transcribe(file);
                }}
              />
              <AudioLines
                size={20}
                className="ml-auto shrink-0 text-brand-600"
              />
            </label>
            <label htmlFor="transcript" className="field-label mt-5">
              What was discussed?
            </label>
            <textarea
              id="transcript"
              className="field min-h-64"
              value={transcript}
              disabled={!!busy}
              onChange={(event) => {
                setTranscript(event.target.value);
                reset();
              }}
              placeholder="Paste the consultation transcript: observations, assessment and plan as discussed."
            />
            <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5">
              <span className="text-xs text-muted">
                {encounterId
                  ? `For ${consultation?.patient_name ?? 'the selected patient'}`
                  : 'Start a consultation in step 1 first'}
              </span>
              <Button
                onClick={() => void generate()}
                busy={busy === 'draft'}
                disabled={
                  !!busy || !encounterId || transcript.trim().length < 10
                }
              >
                <WandSparkles size={16} />
                {busy === 'draft' ? 'Preparing draft…' : 'Generate SOAP draft'}
              </Button>
            </div>
          </div>
        </div>

        <div className="panel overflow-hidden">
          <div className="flex items-center gap-3 border-b border-line px-6 py-5">
            <HeartPulse size={18} className="text-brand-600" />
            <h2 className="text-sm font-semibold">Review and sign</h2>
            <span className="ml-auto text-[11px] text-muted">Step 3</span>
          </div>
          {session?.status === 'signed' && session.signed ? (
            <div className="p-6" role="status">
              <Badge tone="green">
                Signed · version {session.signed.version}
              </Badge>
              <p className="mt-4 flex items-center gap-2 text-sm font-semibold">
                <ShieldCheck size={16} className="text-brand-600" />
                Note signed and saved with its prescriptions.
              </p>
              <p className="mt-2 break-all text-[11px] text-muted">
                Note {session.signed.note_id} · hash{' '}
                {session.signed.content_hash}
              </p>
            </div>
          ) : reviewing ? (
            <div className="space-y-5 p-6">
              <Badge tone="amber">Review required · Unsigned</Badge>
              {session.drafting_unavailable && (
                <p className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
                  Automatic drafting is unavailable right now. Write the note
                  below and sign it as usual.
                </p>
              )}
              {FIELDS.map((key) => (
                <div key={key}>
                  <label
                    htmlFor={`soap-${key}`}
                    className="field-label capitalize"
                  >
                    {key}
                  </label>
                  <textarea
                    id={`soap-${key}`}
                    className="field min-h-20"
                    value={soap[key]}
                    disabled={!!busy}
                    onChange={(event) =>
                      setSoap({ ...soap, [key]: event.target.value })
                    }
                  />
                </div>
              ))}
              <div>
                <label htmlFor="soap-medicines" className="field-label">
                  Medicines (comma separated)
                </label>
                <input
                  id="soap-medicines"
                  className="field"
                  value={soap.medicines.join(', ')}
                  disabled={!!busy}
                  onChange={(event) =>
                    setSoap({
                      ...soap,
                      medicines: event.target.value
                        .split(',')
                        .map((item) => item.trim())
                        .filter(Boolean),
                    })
                  }
                />
                <ul className="mt-3 space-y-1.5" aria-label="Stock">
                  {session.stock_flags.map((flag) => (
                    <li
                      key={flag.medicine}
                      className="flex items-center justify-between gap-3 text-xs"
                    >
                      <span>{flag.medicine}</span>
                      <Badge tone={STOCK_LABEL[flag.status].tone}>
                        {STOCK_LABEL[flag.status].text(flag)}
                      </Badge>
                    </li>
                  ))}
                </ul>
                {session.rejected_medicines.length > 0 && (
                  <p className="mt-3 rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-800">
                    Not added because they were not mentioned in the
                    consultation: {session.rejected_medicines.join(', ')}.
                  </p>
                )}
              </div>
              <div className="flex flex-wrap gap-2 border-t border-line pt-5">
                <Button
                  variant="secondary"
                  className="text-xs"
                  busy={busy === 'edit'}
                  disabled={!!busy}
                  onClick={() => void decide('edit')}
                >
                  <PenLine size={14} />
                  Save edits &amp; re-check stock
                </Button>
                <Button
                  className="ml-auto text-xs"
                  busy={busy === 'sign'}
                  disabled={!!busy}
                  onClick={() => void decide('sign')}
                >
                  <ShieldCheck size={14} />
                  Sign note
                </Button>
              </div>
              <div>
                <label htmlFor="reject-comments" className="field-label">
                  Not right? Tell the scribe what to fix
                </label>
                <div className="flex gap-2">
                  <input
                    id="reject-comments"
                    className="field"
                    value={comments}
                    disabled={!!busy}
                    onChange={(event) => setComments(event.target.value)}
                  />
                  <Button
                    variant="secondary"
                    className="shrink-0 text-xs"
                    busy={busy === 'reject'}
                    disabled={!!busy}
                    onClick={() => void decide('reject')}
                  >
                    <RotateCcw size={14} />
                    Reject &amp; redraft
                  </Button>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex min-h-[450px] flex-col items-center justify-center p-6">
              <EmptyState
                icon={<FilePenLine size={25} />}
                title={
                  busy === 'draft'
                    ? 'Organizing your consultation…'
                    : 'A clear note starts with a conversation.'
                }
                description="Choose a consultation, add the transcript, and review the SOAP draft here."
              />
            </div>
          )}
        </div>
      </div>
      <div className="mt-6">
        <PrivacyNote>
          Audio is processed locally and never saved. Nothing is written to the
          record until you sign, and medicines must be named in the
          consultation.
        </PrivacyNote>
      </div>
    </section>
  );
}
