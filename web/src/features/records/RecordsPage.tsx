import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  ArrowUp,
  BookOpen,
  Check,
  ChevronDown,
  FileText,
  HeartPulse,
  Plus,
  UploadCloud,
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

type Answer = {
  status: string;
  answer: string;
  citations: { chunk_id: string; doc_id: string; page: number; text: string }[];
};
type HealthRecord = {
  doc_id: string;
  status: string | null;
  error: string | null;
  uploaded_at: string;
  type: string;
};
type Message = {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  answer?: Answer;
};
const suggestions = [
  'What does my report say about LDL?',
  'Help me understand my latest results',
];

export function RecordsPage() {
  const { auth } = useAuth();
  const [question, setQuestion] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [error, setError] = useState('');
  const [uploadError, setUploadError] = useState('');
  const [asking, setAsking] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [uploadSuccess, setUploadSuccess] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const {
    data: records = [],
    refetch,
    isPending,
    error: listError,
  } = useQuery({
    queryKey: ['records', auth.user_id, auth.role],
    queryFn: () => api<HealthRecord[]>('/api/records', {}, auth),
    retry: false,
  });
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [messages, asking]);
  async function ask(value = question) {
    if (!value.trim() || asking) return;
    setAsking(true);
    setError('');
    setQuestion('');
    setMessages((previous) => [
      ...previous,
      { id: crypto.randomUUID(), role: 'user', text: value },
    ]);
    try {
      const answer = await api<Answer>(
        '/api/records/questions',
        { method: 'POST', body: JSON.stringify({ question: value }) },
        auth,
      );
      setMessages((previous) => [
        ...previous,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          text: answer.answer,
          answer,
        },
      ]);
    } catch (cause) {
      setError(humanError(cause));
      setQuestion(value);
    } finally {
      setAsking(false);
    }
  }
  async function upload() {
    if (!file || uploading) return;
    setUploading(true);
    setUploadError('');
    setUploadSuccess(false);
    const data = new FormData();
    data.set('file', file);
    data.set('patient_id', auth.acting_for_patient_id ?? '');
    try {
      await api('/api/records', { method: 'POST', body: data }, auth);
      await refetch();
      setFile(null);
      if (fileRef.current) fileRef.current.value = '';
      setUploadSuccess(true);
    } catch (cause) {
      setUploadError(humanError(cause));
    } finally {
      setUploading(false);
    }
  }
  return (
    <section>
      <PageHeader
        eyebrow="Your health library"
        title="Your records, in plain words."
        description="Keep your reports together. Ask a question, and find clarity in the source."
        action={
          <Badge>
            <ShieldIcon />
            Private to your care circle
          </Badge>
        }
      />
      <div className="grid items-start gap-6 xl:grid-cols-[300px_minmax(0,1fr)]">
        <aside id="record-library" className="order-2 space-y-5 xl:order-1">
          {auth.role === 'patient' && (
            <div className="panel p-5">
              <h2 className="text-sm font-semibold">Add a health record</h2>
              <p className="mb-4 mt-1.5 text-xs leading-relaxed text-muted">
                Lab reports, prescriptions, or visit summaries.
              </p>
              <label className="relative flex cursor-pointer flex-col items-center rounded-xl border border-dashed border-brand-200 bg-brand-50/40 px-3 py-6 text-center hover:bg-brand-50 focus-within:ring-2 focus-within:ring-brand-600">
                <input
                  ref={fileRef}
                  type="file"
                  className="sr-only"
                  accept=".pdf,.txt,application/pdf,text/plain"
                  disabled={uploading}
                  onChange={(event) => {
                    setFile(event.target.files?.[0] ?? null);
                    setUploadSuccess(false);
                  }}
                />
                <UploadCloud
                  size={23}
                  className="mb-3 text-brand-600"
                  aria-hidden="true"
                />
                <span className="max-w-full break-words text-xs font-semibold">
                  {file?.name ?? 'Choose a file to upload'}
                </span>
                <span className="mt-1.5 text-[11px] text-muted">
                  PDF or text · up to 8 MB
                </span>
              </label>
              <Button
                className="mt-3 w-full"
                variant="secondary"
                busy={uploading}
                disabled={!file}
                onClick={() => void upload()}
              >
                <Plus size={15} />
                {uploading ? 'Adding record…' : 'Add record'}
              </Button>
              <div className="mt-3">
                <ErrorNotice message={uploadError} />
              </div>
              {uploadSuccess && (
                <p
                  role="status"
                  className="mt-3 flex items-center gap-2 text-xs text-brand-700"
                >
                  <Check size={14} />
                  Your record is ready.
                </p>
              )}
            </div>
          )}
          <div className="panel overflow-hidden">
            <div className="flex items-center justify-between border-b border-line px-5 py-4">
              <h2 className="text-sm font-semibold">Your documents</h2>
              <Badge>{records.length}</Badge>
            </div>
            {isPending ? (
              <p role="status" className="p-5 text-xs text-muted">
                Loading your records…
              </p>
            ) : listError ? (
              <div className="p-4">
                <ErrorNotice message={humanError(listError)} />
              </div>
            ) : records.length === 0 ? (
              <EmptyState
                icon={<FileText size={21} />}
                title="A home for your health records"
                description={
                  auth.role === 'patient'
                    ? 'Add a report to start asking questions about it.'
                    : 'Records shared with this identity will appear here.'
                }
              />
            ) : (
              <ul className="divide-y divide-line">
                {records.map((record, index) => (
                  <li key={record.doc_id} className="px-5 py-4">
                    <div className="flex items-start gap-3">
                      <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-line bg-canvas text-muted">
                        <FileText size={17} />
                      </span>
                      <div className="min-w-0">
                        <h3 className="text-xs font-semibold">
                          Health record {records.length - index}
                        </h3>
                        <p className="mt-1 text-[11px] text-muted">
                          {formatDate(record.uploaded_at)}
                        </p>
                        <div className="mt-2">
                          <Badge
                            tone={record.status === 'ready' ? 'green' : 'amber'}
                          >
                            {record.status?.replaceAll('_', ' ') ?? 'Pending'}
                          </Badge>
                        </div>
                      </div>
                    </div>
                    {record.error && (
                      <p className="mt-2 text-xs text-red-700">
                        {record.error.replaceAll('_', ' ')}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="px-1">
            <PrivacyNote>
              Answers use only the records you’re allowed to access, with
              citations you can check.
            </PrivacyNote>
          </div>
        </aside>
        <div className="panel order-1 min-w-0 overflow-hidden xl:order-2">
          <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-4">
            <div className="flex items-center gap-3">
              <span className="flex size-9 items-center justify-center rounded-xl bg-brand-700 text-white">
                <BookOpen size={18} />
              </span>
              <div>
                <h2 className="text-sm font-semibold">Ask your records</h2>
                <p className="mt-0.5 text-[11px] text-muted">
                  Answers grounded in your documents
                </p>
              </div>
            </div>
            <Badge tone="green">With sources</Badge>
          </div>
          <div
            ref={logRef}
            role="log"
            aria-label="Records conversation"
            aria-live="polite"
            aria-relevant="additions"
            className="h-[280px] sm:h-[clamp(320px,calc(100dvh-560px),500px)] space-y-7 overflow-y-auto px-5 py-7 sm:px-7"
          >
            <div className="flex gap-3">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-brand-700 text-white">
                <HeartPulse size={17} />
              </span>
              <div className="min-w-0">
                <p className="mb-2 text-xs font-semibold">MedPal</p>
                <p className="text-sm leading-7 text-slate-700">
                  Health reports can be a lot to take in. Ask me a question
                  about yours, and I’ll help you understand what’s there — with
                  the exact source.
                </p>
                {messages.length === 0 && (
                  <div className="mt-4 flex flex-wrap gap-2">
                    {suggestions.map((suggestion) => (
                      <button
                        key={suggestion}
                        disabled={asking}
                        onClick={() => void ask(suggestion)}
                        className="min-h-11 rounded-xl border border-line px-3 py-2 text-left text-xs text-muted hover:border-brand-200 hover:bg-brand-50"
                      >
                        {suggestion}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
            {messages.map((message) =>
              message.role === 'user' ? (
                <div key={message.id} className="flex justify-end pl-10">
                  <p className="max-w-[90%] whitespace-pre-wrap rounded-2xl rounded-tr-sm bg-brand-50 px-4 py-3 text-sm leading-relaxed text-brand-900">
                    {message.text}
                  </p>
                </div>
              ) : (
                <div key={message.id} className="flex gap-3">
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-brand-700 text-white">
                    <HeartPulse size={17} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="mb-2 text-xs font-semibold">MedPal</p>
                    <p className="whitespace-pre-wrap text-sm leading-7 text-slate-700">
                      {message.text}
                    </p>
                    {message.answer?.status === 'needs_doctor' && (
                      <div className="mt-3">
                        <Badge tone="amber">
                          Your doctor can help with this
                        </Badge>
                      </div>
                    )}
                    {!!message.answer?.citations.length && (
                      <div className="mt-4 rounded-xl border border-line bg-canvas p-3">
                        <p className="eyebrow mb-2">
                          Sources · {message.answer.citations.length}
                        </p>
                        {message.answer.citations.map((citation, index) => (
                          <details
                            key={`${citation.chunk_id}-${index}`}
                            className="group border-t border-line first-of-type:border-0"
                          >
                            <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 text-xs font-medium text-brand-800">
                              <FileText size={14} />
                              Source {index + 1} · Page {citation.page}
                              <ChevronDown
                                size={13}
                                className="ml-auto transition-transform group-open:rotate-180"
                              />
                            </summary>
                            <blockquote className="mb-3 border-l-2 border-brand-200 pl-3 text-xs leading-6 text-muted">
                              {citation.text}
                            </blockquote>
                          </details>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ),
            )}
            {asking && (
              <p
                role="status"
                className="flex items-center gap-2 text-xs text-muted"
              >
                <span className="size-2 animate-pulse rounded-full bg-brand-500" />
                Reading your records…
              </p>
            )}
          </div>
          <div className="border-t border-line p-4 sm:p-5">
            <ErrorNotice message={error} />
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void ask();
              }}
              className={`flex items-end gap-3 rounded-2xl border border-slate-300 p-3 focus-within:border-brand-500 focus-within:ring-2 focus-within:ring-brand-100 ${error ? 'mt-3' : ''}`}
            >
              <label htmlFor="record-question" className="sr-only">
                Question about your records
              </label>
              <textarea
                id="record-question"
                rows={2}
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder="Ask something about your records…"
                disabled={asking}
                className="w-full resize-none bg-transparent px-1 py-1 text-base leading-relaxed placeholder:text-slate-500 focus-visible:ring-0 sm:text-sm"
                onKeyDown={(event) => {
                  if (
                    event.key === 'Enter' &&
                    !event.shiftKey &&
                    !event.nativeEvent.isComposing
                  ) {
                    event.preventDefault();
                    void ask();
                  }
                }}
              />
              <button
                aria-label="Send question"
                disabled={asking || !question.trim()}
                className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-brand-700 text-white hover:bg-brand-800 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <ArrowUp size={20} />
              </button>
            </form>
            <p className="mt-3 text-center text-[10px] leading-relaxed text-muted">
              For understanding your records. Decisions about diagnosis or
              treatment belong with your doctor.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
function ShieldIcon() {
  return <Check size={11} aria-hidden="true" />;
}
