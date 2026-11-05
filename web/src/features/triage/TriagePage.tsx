import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowRight,
  ArrowUp,
  CalendarDays,
  Check,
  CheckCircle2,
  ChevronRight,
  Clock3,
  HeartPulse,
  MapPin,
  MessageCircle,
  Plus,
  Stethoscope,
} from 'lucide-react';
import { Link } from 'react-router-dom';
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

interface Candidate {
  slot_id: string;
  doctor_name: string;
  clinic_name: string;
  display_time: string;
}
interface SafetyQuestion {
  key: string;
  question: string;
}
interface TriageOut {
  thread_id: string;
  status: string;
  reply?: string;
  candidates?: Candidate[];
  safety_questions?: SafetyQuestion[];
  booking_id?: string;
  specialty?: string;
}
interface Message {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  result?: TriageOut;
  chosen?: Candidate;
}
interface Appointment {
  appt_id: string;
  doctor_name: string;
  clinic_name: string;
  starts_at: string;
  status: string;
}
const prompts = [
  'I’ve had knee pain for a week',
  'I need help with a skin rash',
  'I have a recurring headache',
];

function describe(result: TriageOut): string {
  if (result.status === 'awaiting_choice')
    return `I found ${result.candidates?.length ?? 0} available options${result.specialty ? ` in ${result.specialty.toLowerCase()}` : ''}. Choose the appointment that works best for you.`;
  if (result.status === 'awaiting_safety_check')
    return (
      result.reply ??
      'Before we book, please answer a few quick safety questions.'
    );
  return result.reply ?? 'Your request has been sent to the clinic team.';
}

/** One explicit Yes/No per red-flag question. No "no to all" shortcut: each must be read. */
export function SafetyCheck({
  questions,
  disabled,
  onSubmit,
}: {
  questions: SafetyQuestion[];
  disabled: boolean;
  onSubmit: (answers: Record<string, boolean>) => void;
}) {
  const [answers, setAnswers] = useState<Record<string, boolean>>({});
  const complete = questions.every((q) => q.key in answers);
  return (
    <form
      className="mt-4 space-y-2.5"
      aria-label="Safety questions"
      onSubmit={(event) => {
        event.preventDefault();
        if (complete && !disabled) onSubmit(answers);
      }}
    >
      {questions.map((q) => (
        <fieldset
          key={q.key}
          className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line p-3"
        >
          <legend className="sr-only">{q.question}</legend>
          <span className="text-sm text-slate-700" aria-hidden="true">
            {q.question}
          </span>
          <span className="flex gap-2">
            {([true, false] as const).map((value) => (
              <label
                key={String(value)}
                className={`cursor-pointer rounded-lg border px-3 py-1 text-xs font-medium ${
                  answers[q.key] === value
                    ? value
                      ? 'border-red-300 bg-red-50 text-red-800'
                      : 'border-brand-300 bg-brand-50 text-brand-800'
                    : 'border-line text-muted'
                }`}
              >
                <input
                  type="radio"
                  className="sr-only"
                  name={q.key}
                  disabled={disabled}
                  checked={answers[q.key] === value}
                  onChange={() =>
                    setAnswers((previous) => ({ ...previous, [q.key]: value }))
                  }
                />
                {value ? 'Yes' : 'No'}
              </label>
            ))}
          </span>
        </fieldset>
      ))}
      <Button
        type="submit"
        disabled={disabled || !complete}
        className="text-xs"
      >
        Continue
        <ArrowRight size={13} />
      </Button>
    </form>
  );
}

function AssistantAvatar() {
  return (
    <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-xl bg-brand-700 text-white">
      <HeartPulse size={17} strokeWidth={1.7} aria-hidden="true" />
    </span>
  );
}

export function TriagePage() {
  const { auth } = useAuth();
  const client = useQueryClient();
  const [text, setText] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [active, setActive] = useState<TriageOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const logRef = useRef<HTMLDivElement>(null);
  const keys = useRef(new Map<string, string>());
  const {
    data: appointments = [],
    isPending,
    error: appointmentError,
  } = useQuery({
    queryKey: ['appointments', auth.user_id],
    queryFn: () => api<Appointment[]>('/api/appointments', {}, auth),
    retry: false,
  });
  const upcoming = appointments
    .filter(
      (item) =>
        item.status === 'booked' && new Date(item.starts_at) > new Date(),
    )
    .sort((a, b) => a.starts_at.localeCompare(b.starts_at));
  useEffect(() => {
    const log = logRef.current;
    if (log) {
      const latest = log.querySelector('[data-latest="true"]');
      log.scrollTop = latest
        ? latest.getBoundingClientRect().top -
          log.getBoundingClientRect().top +
          log.scrollTop -
          24
        : log.scrollHeight;
    }
  }, [messages, busy]);

  async function start(value = text) {
    if (busy || value.trim().length < 3) return;
    if (active?.status === 'awaiting_clarification')
      return clarify(active, value);
    setBusy(true);
    setError('');
    setText('');
    setActive(null);
    setMessages((previous) => [
      ...previous,
      { id: crypto.randomUUID(), role: 'user', text: value.trim() },
    ]);
    try {
      const result = await api<TriageOut>(
        '/triage',
        { method: 'POST', body: JSON.stringify({ text: value.trim() }) },
        auth,
      );
      setActive(result);
      setMessages((previous) => [
        ...previous,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          text: describe(result),
          result,
        },
      ]);
    } catch (cause) {
      setError(humanError(cause));
      setText(value);
    } finally {
      setBusy(false);
    }
  }

  /** The assistant asked a clarifying question: the next message answers it, in the same run. */
  async function clarify(result: TriageOut, value: string) {
    setBusy(true);
    setError('');
    setText('');
    setMessages((previous) => [
      ...previous,
      { id: crypto.randomUUID(), role: 'user', text: value.trim() },
    ]);
    try {
      const response = await api<TriageOut>(
        `/triage/${result.thread_id}/resume`,
        { method: 'POST', body: JSON.stringify({ answer: value.trim() }) },
        auth,
      );
      setActive(response);
      setMessages((previous) => [
        ...previous,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          text: describe(response),
          result: response,
        },
      ]);
    } catch (cause) {
      setError(humanError(cause));
      setText(value);
    } finally {
      setBusy(false);
    }
  }

  async function answerSafety(
    result: TriageOut,
    answers: Record<string, boolean>,
  ) {
    if (
      busy ||
      active?.thread_id !== result.thread_id ||
      active?.status !== 'awaiting_safety_check'
    )
      return;
    setBusy(true);
    setError('');
    try {
      const response = await api<TriageOut>(
        `/triage/${result.thread_id}/resume`,
        { method: 'POST', body: JSON.stringify({ safety_answers: answers }) },
        auth,
      );
      const yes = Object.values(answers).some(Boolean);
      setActive(response);
      setMessages((previous) => [
        ...previous,
        {
          id: crypto.randomUUID(),
          role: 'user',
          text: yes
            ? 'I answered yes to a safety question.'
            : 'None of these apply to me.',
        },
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          text: describe(response),
          result: response,
        },
      ]);
    } catch (cause) {
      setError(humanError(cause));
    } finally {
      setBusy(false);
    }
  }

  async function book(result: TriageOut, candidate: Candidate) {
    if (
      busy ||
      active?.thread_id !== result.thread_id ||
      active?.status !== 'awaiting_choice'
    )
      return;
    setBusy(true);
    setError('');
    const attempt = `${result.thread_id}:${candidate.slot_id}`;
    const key = keys.current.get(attempt) ?? crypto.randomUUID();
    keys.current.set(attempt, key);
    try {
      const response = await api<TriageOut>(
        `/triage/${result.thread_id}/resume`,
        {
          method: 'POST',
          body: JSON.stringify({
            slot_id: candidate.slot_id,
            idempotency_key: key,
          }),
        },
        auth,
      );
      setActive(response);
      setMessages((previous) => [
        ...previous,
        {
          id: crypto.randomUUID(),
          role: 'user',
          text: `Book my visit with ${candidate.doctor_name}.`,
        },
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          text:
            response.status === 'booked'
              ? 'You’re all set. Your appointment is confirmed.'
              : (response.reply ??
                'That slot is no longer available. Please choose another option.'),
          result: response,
          chosen: response.status === 'booked' ? candidate : undefined,
        },
      ]);
      if (response.status === 'booked')
        await client.invalidateQueries({
          queryKey: ['appointments', auth.user_id],
        });
    } catch (cause) {
      setError(humanError(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <PageHeader
        eyebrow="Your personal care space"
        title="Hi Asha, how can I help?"
        description="A clearer path to the right care, one conversation at a time."
      />
      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_290px]">
        <div className="panel min-w-0 overflow-hidden">
          <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-4 sm:px-6">
            <div className="flex items-center gap-3">
              <AssistantAvatar />
              <div>
                <h2 className="text-sm font-semibold">MedPal assistant</h2>
                <p className="mt-0.5 text-[11px] text-muted">
                  Here to help you find care
                </p>
              </div>
            </div>
            <button
              onClick={() => {
                setMessages([]);
                setActive(null);
                setError('');
                setText('');
              }}
              disabled={busy || messages.length === 0}
              className="btn btn-ghost px-2.5 text-xs"
              aria-label="New conversation"
            >
              <Plus size={16} />
              <span className="hidden sm:inline">New chat</span>
            </button>
          </div>
          <div
            ref={logRef}
            role="log"
            aria-label="Care conversation"
            aria-live="polite"
            aria-relevant="additions"
            className="relative h-[280px] space-y-7 overflow-y-auto px-5 py-7 sm:h-[clamp(320px,calc(100dvh-560px),500px)] sm:px-7"
          >
            <div className="flex gap-3">
              <AssistantAvatar />
              <div className="max-w-[90%]">
                <p className="mb-2 text-xs font-semibold">MedPal</p>
                <div className="text-sm leading-7 text-slate-700">
                  <p>Hi Asha. Let’s take care of you.</p>
                  <p className="mt-2">
                    Tell me what’s been bothering you and for how long. I’ll
                    help you find the right doctor and a time that works.
                  </p>
                </div>
                {messages.length === 0 && (
                  <div className="mt-5 flex flex-col items-start gap-2">
                    {prompts.map((prompt) => (
                      <button
                        key={prompt}
                        onClick={() => void start(prompt)}
                        disabled={busy}
                        className="flex min-h-11 max-w-full items-center gap-3 rounded-xl border border-line bg-white px-3.5 py-2.5 text-left text-xs text-slate-600 hover:border-brand-200 hover:bg-brand-50"
                      >
                        {prompt}
                        <ArrowRight
                          size={14}
                          className="shrink-0 text-brand-600"
                        />
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
            {messages.map((message, index) =>
              message.role === 'user' ? (
                <div
                  key={message.id}
                  data-latest={index === messages.length - 1}
                  className="flex justify-end pl-10"
                >
                  <div className="max-w-[92%] whitespace-pre-wrap rounded-2xl rounded-tr-sm bg-brand-50 px-4 py-3 text-sm leading-relaxed text-brand-900">
                    {message.text}
                  </div>
                </div>
              ) : (
                <div
                  key={message.id}
                  data-latest={index === messages.length - 1}
                  className="flex gap-3"
                >
                  <AssistantAvatar />
                  <div className="min-w-0 flex-1">
                    <p className="mb-2 text-xs font-semibold">MedPal</p>
                    <div
                      className={`text-sm leading-7 ${message.result?.status === 'emergency' ? 'rounded-xl border border-red-200 bg-red-50 p-4 text-red-800' : 'text-slate-700'}`}
                    >
                      {message.text}
                    </div>
                    {message.result?.status === 'awaiting_safety_check' &&
                      message.result.safety_questions && (
                        <SafetyCheck
                          questions={message.result.safety_questions}
                          disabled={
                            busy ||
                            active?.thread_id !== message.result.thread_id ||
                            active?.status !== 'awaiting_safety_check'
                          }
                          onSubmit={(answers) =>
                            void answerSafety(message.result!, answers)
                          }
                        />
                      )}
                    {message.result?.candidates && (
                      <div className="mt-4 space-y-2.5">
                        {message.result.candidates.map((candidate) => (
                          <article
                            key={candidate.slot_id}
                            className="rounded-xl border border-line p-4"
                          >
                            <div className="flex items-start gap-3">
                              <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-[#f1eee7] text-xs font-semibold text-[#6d6048]">
                                {candidate.doctor_name
                                  .split(' ')
                                  .map((name) => name[0])
                                  .slice(0, 2)
                                  .join('')}
                              </span>
                              <div className="min-w-0">
                                <h3 className="text-sm font-semibold">
                                  {candidate.doctor_name}
                                </h3>
                                <p className="mt-1 text-xs text-muted">
                                  {message.result?.specialty ??
                                    'Clinic appointment'}
                                </p>
                              </div>
                            </div>
                            <p className="mt-3 flex items-center gap-2 text-xs text-muted">
                              <MapPin size={13} />
                              {candidate.clinic_name}
                            </p>
                            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3">
                              <span className="flex items-center gap-2 text-xs font-medium">
                                <CalendarDays
                                  size={14}
                                  className="text-brand-600"
                                />
                                {candidate.display_time} IST
                              </span>
                              <Button
                                variant="secondary"
                                className="px-3 text-xs"
                                busy={
                                  busy &&
                                  active?.thread_id ===
                                    message.result?.thread_id
                                }
                                disabled={
                                  busy ||
                                  active?.thread_id !==
                                    message.result?.thread_id ||
                                  active?.status !== 'awaiting_choice'
                                }
                                onClick={() =>
                                  void book(message.result!, candidate)
                                }
                              >
                                Choose time
                                <ArrowRight size={13} />
                              </Button>
                            </div>
                          </article>
                        ))}
                      </div>
                    )}
                    {message.result?.booking_id && (
                      <div className="mt-4 rounded-xl border border-brand-200 bg-brand-50 p-4">
                        <div className="flex items-center gap-2 text-sm font-semibold text-brand-800">
                          <CheckCircle2 size={18} />
                          Appointment confirmed
                        </div>
                        {message.chosen && (
                          <div className="mt-3 space-y-2 text-xs text-brand-900">
                            <p className="font-semibold">
                              {message.chosen.doctor_name}
                            </p>
                            <p className="flex items-center gap-2">
                              <MapPin size={13} />
                              {message.chosen.clinic_name}
                            </p>
                            <p className="flex items-center gap-2">
                              <CalendarDays size={13} />
                              {message.chosen.display_time} IST
                            </p>
                          </div>
                        )}
                        <details className="mt-3 text-xs text-muted">
                          <summary className="cursor-pointer py-2">
                            Booking reference
                          </summary>
                          <span className="break-all font-mono">
                            {message.result.booking_id}
                          </span>
                        </details>
                      </div>
                    )}
                  </div>
                </div>
              ),
            )}
            {busy && (
              <div className="flex items-center gap-3" role="status">
                <AssistantAvatar />
                <span className="text-xs text-muted">
                  {active
                    ? 'Confirming your appointment…'
                    : 'Checking care options…'}
                </span>
                <span className="flex gap-1" aria-hidden="true">
                  {[0, 1, 2].map((dot) => (
                    <span
                      key={dot}
                      className="size-1.5 animate-pulse rounded-full bg-brand-500"
                      style={{ animationDelay: `${dot * 160}ms` }}
                    />
                  ))}
                </span>
              </div>
            )}
          </div>
          <div className="border-t border-line bg-white p-4 sm:p-5">
            <ErrorNotice message={error} />
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void start();
              }}
              className={`rounded-2xl border border-slate-300 bg-white p-3 shadow-xs focus-within:border-brand-500 focus-within:ring-2 focus-within:ring-brand-100 ${error ? 'mt-3' : ''}`}
            >
              <label htmlFor="care-message" className="sr-only">
                Tell MedPal how you’re feeling
              </label>
              <textarea
                id="care-message"
                value={text}
                onChange={(event) => setText(event.target.value)}
                placeholder="Tell me how you’re feeling…"
                rows={2}
                maxLength={2000}
                disabled={busy}
                className="block w-full resize-none border-0 bg-transparent px-1 py-1 text-base leading-relaxed placeholder:text-slate-500 focus-visible:ring-0 sm:text-sm"
                onKeyDown={(event) => {
                  if (
                    event.key === 'Enter' &&
                    !event.shiftKey &&
                    !event.nativeEvent.isComposing
                  ) {
                    event.preventDefault();
                    void start();
                  }
                }}
              />
              <div className="mt-2 flex items-center justify-between gap-3">
                <span className="px-1 text-[11px] text-muted">
                  English or Hinglish. In your own words.
                </span>
                <button
                  type="submit"
                  disabled={busy || text.trim().length < 3}
                  aria-label="Send message"
                  className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-brand-700 text-white hover:bg-brand-800 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <ArrowUp size={20} />
                </button>
              </div>
            </form>
            <p className="mt-3 text-center text-[10px] leading-relaxed text-muted">
              Care navigation, not a diagnosis. For urgent symptoms, seek
              emergency care.
            </p>
          </div>
        </div>
        <aside className="space-y-5">
          <div className="panel overflow-hidden">
            <div className="flex items-center justify-between border-b border-line px-5 py-4">
              <h2 className="text-sm font-semibold">Your next visit</h2>
              <CalendarDays size={16} className="text-muted" />
            </div>
            {isPending ? (
              <p role="status" className="p-5 text-xs text-muted">
                Loading appointments…
              </p>
            ) : appointmentError ? (
              <div className="p-4">
                <ErrorNotice message="Appointments couldn’t load. Refresh to try again." />
              </div>
            ) : upcoming.length ? (
              <div className="p-5">
                <Badge tone="green">
                  <Check size={11} />
                  Confirmed
                </Badge>
                <h3 className="mt-4 text-sm font-semibold">
                  {upcoming[0].doctor_name}
                </h3>
                <p className="mt-1 text-xs text-muted">
                  {upcoming[0].clinic_name}
                </p>
                <p className="mt-5 flex items-start gap-2 border-t border-line pt-4 text-xs leading-relaxed">
                  <Clock3 size={15} className="shrink-0 text-brand-600" />
                  {new Intl.DateTimeFormat('en-IN', {
                    day: 'numeric',
                    month: 'short',
                    weekday: 'short',
                    hour: '2-digit',
                    minute: '2-digit',
                    timeZone: 'Asia/Kolkata',
                  }).format(new Date(upcoming[0].starts_at))}{' '}
                  IST
                </p>
                {upcoming.length > 1 && (
                  <p className="mt-3 text-xs text-muted">
                    +{upcoming.length - 1} more upcoming{' '}
                    {upcoming.length === 2 ? 'visit' : 'visits'}
                  </p>
                )}
              </div>
            ) : (
              <EmptyState
                icon={<CalendarDays size={22} />}
                title="A little care starts here"
                description="Once you book a visit, you’ll find the details here."
              />
            )}
          </div>
          <div className="rounded-2xl border border-brand-100 bg-brand-50 p-5">
            <div className="mb-4 flex size-10 items-center justify-center rounded-xl border border-brand-200 bg-white/70 text-brand-700">
              <MessageCircle size={19} />
            </div>
            <h2 className="text-sm font-semibold text-brand-900">
              Your records, explained.
            </h2>
            <p className="mt-2 text-xs leading-6 text-brand-800">
              Have a question about a report? Ask your records and get an answer
              with sources.
            </p>
            <Link
              to="/records"
              className="mt-3 inline-flex min-h-11 items-center gap-2 text-xs font-semibold text-brand-800"
            >
              Ask my records
              <ChevronRight size={14} />
            </Link>
          </div>
          <div className="px-1">
            <p className="eyebrow mb-4">A thoughtful next step</p>
            <div className="space-y-4">
              {[
                {
                  icon: MessageCircle,
                  title: 'Tell me what’s going on',
                  text: 'A few words about your symptoms.',
                },
                {
                  icon: Stethoscope,
                  title: 'Explore your options',
                  text: 'Find available care near you.',
                },
                {
                  icon: CalendarDays,
                  title: 'Choose your visit',
                  text: 'You make the final choice.',
                },
              ].map(({ icon: Icon, title, text: detail }, index) => (
                <div key={title} className="flex items-start gap-3">
                  <span className="flex size-7 shrink-0 items-center justify-center rounded-full border border-line bg-white text-[10px] font-semibold text-muted">
                    {index + 1}
                  </span>
                  <div>
                    <p className="text-xs font-medium">{title}</p>
                    <p className="mt-1 text-[11px] leading-relaxed text-muted">
                      {detail}
                    </p>
                  </div>
                  <Icon
                    size={14}
                    className="ml-auto mt-1 shrink-0 text-slate-400"
                  />
                </div>
              ))}
            </div>
            <div className="mt-6 border-t border-line pt-4">
              <PrivacyNote>
                Only the details needed for your care. Always under your
                control.
              </PrivacyNote>
            </div>
          </div>
        </aside>
      </div>
    </section>
  );
}
