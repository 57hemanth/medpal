import { useState } from 'react';
import {
  AudioLines,
  Check,
  FilePenLine,
  HeartPulse,
  Mic,
  NotebookPen,
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
  humanError,
} from '../../components/ui';

type Draft = {
  subjective: string;
  objective: string;
  assessment: string;
  plan: string;
  medicines: string[];
};
export function ScribePage() {
  const { auth } = useAuth();
  const [transcript, setTranscript] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState<'draft' | 'audio' | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  async function generate() {
    if (busy || transcript.trim().length < 10) return;
    setBusy('draft');
    setError('');
    setDraft(null);
    try {
      setDraft(
        await api<Draft>(
          '/api/scribe/draft',
          { method: 'POST', body: JSON.stringify({ transcript }) },
          auth,
        ),
      );
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
      setDraft(null);
    } catch (cause) {
      setError(humanError(cause));
    } finally {
      setBusy(null);
    }
  }
  return (
    <section>
      <PageHeader
        eyebrow="Your clinical copilot"
        title="More listening. Less note-taking."
        description="Turn a consultation transcript into a structured SOAP draft, ready for your review."
        action={<Badge tone="amber">Drafting workspace</Badge>}
      />
      <div className="mb-6">
        <ErrorNotice message={error} />
      </div>
      <div className="grid items-start gap-6 xl:grid-cols-2">
        <div className="panel overflow-hidden">
          <div className="flex items-center gap-3 border-b border-line px-6 py-5">
            <NotebookPen size={18} className="text-brand-600" />
            <h2 className="text-sm font-semibold">Consultation transcript</h2>
            <span className="ml-auto text-[11px] text-muted">Step 1</span>
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
            <div className="my-5 flex items-center gap-3">
              <span className="h-px flex-1 bg-line" />
              <span className="text-[11px] text-muted">
                or paste a transcript
              </span>
              <span className="h-px flex-1 bg-line" />
            </div>
            <label htmlFor="transcript" className="field-label">
              What was discussed?
            </label>
            <textarea
              id="transcript"
              className="field min-h-64"
              value={transcript}
              disabled={!!busy}
              onChange={(event) => {
                setTranscript(event.target.value);
                setDraft(null);
              }}
              placeholder="Paste your consultation transcript here. Include the observations, assessment, and plan discussed with the patient."
            />
            <p className="mt-2 text-[11px] text-muted">
              Review the transcript for accuracy before generating a draft.
            </p>
            <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5">
              <span className="text-xs text-muted">
                {transcript.trim() ? transcript.trim().split(/\s+/).length : 0}{' '}
                words
              </span>
              <Button
                onClick={() => void generate()}
                busy={busy === 'draft'}
                disabled={!!busy || transcript.trim().length < 10}
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
            <h2 className="text-sm font-semibold">MedPal draft</h2>
            <span className="ml-auto text-[11px] text-muted">Step 2</span>
          </div>
          {draft ? (
            <div className="p-6">
              <Badge tone="amber">Review required · Unsigned</Badge>
              <div className="mt-6 space-y-6">
                {(
                  ['subjective', 'objective', 'assessment', 'plan'] as const
                ).map((key, index) => (
                  <div key={key}>
                    <div className="mb-2 flex items-center gap-2">
                      <span className="flex size-6 items-center justify-center rounded-lg bg-brand-50 text-[11px] font-bold text-brand-700">
                        {key[0].toUpperCase()}
                      </span>
                      <h3 className="text-sm font-semibold capitalize">
                        {key}
                      </h3>
                    </div>
                    <p className="whitespace-pre-wrap text-sm leading-7 text-slate-700">
                      {draft[key] || 'Not provided in the transcript.'}
                    </p>
                    {index < 3 && <div className="mt-5 h-px bg-line" />}
                  </div>
                ))}
              </div>
              {draft.medicines.length > 0 && (
                <div className="mt-6 rounded-xl bg-canvas p-4">
                  <p className="mb-2 text-xs font-semibold">
                    Medicines mentioned
                  </p>
                  {draft.medicines.map((medicine) => (
                    <p
                      key={medicine}
                      className="flex items-center gap-2 text-xs leading-7 text-muted"
                    >
                      <Check size={12} />
                      {medicine}
                    </p>
                  ))}
                </div>
              )}
              <p className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs leading-relaxed text-amber-900">
                This is an unsigned draft. Clinical review and signing are
                handled separately by your care team.
              </p>
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
                description={
                  busy === 'draft'
                    ? 'Preparing the subjective, objective, assessment, and plan sections.'
                    : 'Add a transcript and MedPal will organize it into a SOAP draft for you to review.'
                }
              />
              <div className="flex gap-2">
                {['S', 'O', 'A', 'P'].map((letter) => (
                  <span
                    key={letter}
                    className={`flex size-9 items-center justify-center rounded-lg border border-line text-xs font-semibold text-muted ${busy === 'draft' ? 'animate-pulse bg-brand-50' : 'bg-canvas'}`}
                  >
                    {letter}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
      <div className="mt-6">
        <PrivacyNote>
          Audio is processed locally and never saved. No note is signed
          automatically.
        </PrivacyNote>
      </div>
    </section>
  );
}
