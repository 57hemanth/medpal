import type { ButtonHTMLAttributes, ReactNode } from 'react';
import {
  AlertCircle,
  ArrowUpRight,
  HeartPulse,
  LoaderCircle,
  ShieldCheck,
} from 'lucide-react';

export function Brand({ light = false }: { light?: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <span
        className={`flex size-8 items-center justify-center rounded-lg ${light ? 'bg-white/15 text-white' : 'bg-brand-700 text-white'}`}
      >
        <HeartPulse size={18} strokeWidth={2} aria-hidden="true" />
      </span>
      <span
        className={`text-[19px] font-bold tracking-[-0.04em] ${light ? 'text-white' : 'text-ink'}`}
      >
        MedPal
      </span>
    </div>
  );
}

export function Button({
  children,
  variant = 'primary',
  busy,
  className = '',
  disabled,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  busy?: boolean;
}) {
  return (
    <button
      className={`btn btn-${variant} ${className}`}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      {...props}
    >
      {busy && (
        <LoaderCircle size={15} className="animate-spin" aria-hidden="true" />
      )}
      {children}
    </button>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <p className="eyebrow mb-1.5">{eyebrow}</p>}
        <h1 className="text-[22px] font-semibold leading-tight tracking-[-0.03em] sm:text-2xl">
          {title}
        </h1>
        {description && (
          <p className="mt-1.5 max-w-2xl text-[13px] leading-relaxed text-muted sm:text-sm">
            {description}
          </p>
        )}
      </div>
      {action && <div className="flex flex-wrap gap-2">{action}</div>}
    </div>
  );
}

export function Card({
  title,
  action,
  children,
  className = '',
  bodyClassName = 'card-body',
}: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || action) && (
        <header className="card-header">
          {title && <h2 className="card-title">{title}</h2>}
          {action}
        </header>
      )}
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone = 'neutral',
  icon,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: 'neutral' | 'green' | 'amber' | 'red';
  icon?: ReactNode;
}) {
  const accents = {
    neutral: 'bg-canvas text-muted',
    green: 'bg-brand-50 text-brand-700',
    amber: 'bg-amber-50 text-amber-700',
    red: 'bg-red-50 text-red-700',
  };
  return (
    <div className="card p-4">
      <div className="flex items-start justify-between gap-3">
        <p className="text-[12px] font-medium text-muted">{label}</p>
        {icon && (
          <span
            className={`flex size-7 items-center justify-center rounded-md ${accents[tone]}`}
            aria-hidden="true"
          >
            {icon}
          </span>
        )}
      </div>
      <p className="mt-2 text-[26px] font-semibold leading-none tracking-[-0.03em]">
        {value}
      </p>
      {hint && <p className="mt-2 text-[12px] text-muted">{hint}</p>}
    </div>
  );
}

export function Badge({
  children,
  tone = 'neutral',
}: {
  children: ReactNode;
  tone?: 'neutral' | 'green' | 'amber' | 'red' | 'blue';
}) {
  const tones = {
    neutral: 'border-line bg-canvas text-muted',
    green: 'border-brand-100 bg-brand-50 text-brand-700',
    amber: 'border-amber-200 bg-amber-50 text-amber-800',
    red: 'border-red-200 bg-red-50 text-red-700',
    blue: 'border-sky-200 bg-sky-50 text-sky-800',
  };
  return <span className={`badge ${tones[tone]}`}>{children}</span>;
}

const STATUS: Record<
  string,
  { label: string; tone: 'neutral' | 'green' | 'amber' | 'red' | 'blue' }
> = {
  booked: { label: 'Booked', tone: 'green' },
  attended: { label: 'Attended', tone: 'neutral' },
  cancelled: { label: 'Cancelled', tone: 'neutral' },
  no_show: { label: 'No-show', tone: 'amber' },
  open: { label: 'Open', tone: 'amber' },
  in_progress: { label: 'In progress', tone: 'blue' },
  closed: { label: 'Closed', tone: 'neutral' },
  emergency: { label: 'Emergency', tone: 'red' },
  front_desk: { label: 'Front desk', tone: 'neutral' },
  records: { label: 'Records', tone: 'blue' },
  review: { label: 'Review', tone: 'amber' },
  ready: { label: 'Ready', tone: 'green' },
  processing: { label: 'Processing', tone: 'blue' },
  queued: { label: 'Queued', tone: 'blue' },
  failed: { label: 'Failed', tone: 'red' },
  signed: { label: 'Signed', tone: 'green' },
};

/** One vocabulary for every status shown in the product. */
export function StatusPill({ status }: { status: string | null | undefined }) {
  const known = STATUS[status ?? ''];
  return (
    <Badge tone={known?.tone ?? 'neutral'}>
      {known?.label ?? (status ?? 'Unknown').replaceAll('_', ' ')}
    </Badge>
  );
}

export function Avatar({ name, size = 32 }: { name: string; size?: number }) {
  const initials = name
    .replace(/^Dr\.?\s+/i, '')
    .split(/\s+/)
    .map((part) => part[0])
    .filter(Boolean)
    .slice(0, 2)
    .join('')
    .toUpperCase();
  return (
    <span
      className="flex shrink-0 items-center justify-center rounded-full bg-[#ebe7dd] text-[11px] font-semibold text-[#5e5440]"
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      {initials || '•'}
    </span>
  );
}

export function Skeleton({ className = 'h-4 w-full' }: { className?: string }) {
  return <span className={`skeleton block ${className}`} aria-hidden="true" />;
}

export function LoadingRows({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-3 p-5" role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, index) => (
        <Skeleton key={index} className="h-10 w-full" />
      ))}
    </div>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div
      role="tablist"
      aria-label={label}
      className="inline-flex rounded-lg border border-line bg-canvas p-0.5"
    >
      {options.map((option) => (
        <button
          key={option.value}
          role="tab"
          aria-selected={value === option.value}
          onClick={() => onChange(option.value)}
          className={`min-h-8 rounded-md px-3 text-[12px] font-semibold ${value === option.value ? 'bg-white text-ink shadow-[var(--shadow-card)]' : 'text-muted hover:text-ink'}`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function ErrorNotice({ message }: { message?: string | null }) {
  if (!message) return null;
  return (
    <div
      role="alert"
      className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 p-3.5 text-[13px] text-red-800"
    >
      <AlertCircle className="mt-0.5 shrink-0" size={16} aria-hidden="true" />
      <p className="min-w-0 break-words leading-relaxed">{message}</p>
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon: ReactNode;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center px-6 py-10 text-center">
      <div
        className="mb-3 flex size-10 items-center justify-center rounded-lg bg-canvas text-muted"
        aria-hidden="true"
      >
        {icon}
      </div>
      <h3 className="text-[13px] font-semibold">{title}</h3>
      <p className="mt-1 max-w-xs text-[13px] leading-relaxed text-muted">
        {description}
      </p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function PrivacyNote({
  children = 'Your information stays within your care team.',
}: {
  children?: ReactNode;
}) {
  return (
    <p className="flex items-start gap-2 text-xs leading-relaxed text-muted">
      <ShieldCheck
        size={14}
        className="mt-0.5 shrink-0 text-brand-600"
        aria-hidden="true"
      />
      {children}
    </p>
  );
}

export function TextLink({
  children,
  ...props
}: React.AnchorHTMLAttributes<HTMLAnchorElement>) {
  return (
    <a
      className="inline-flex items-center gap-1 text-[13px] font-semibold text-brand-700 hover:text-brand-900"
      {...props}
    >
      {children}
      <ArrowUpRight size={14} aria-hidden="true" />
    </a>
  );
}

export function humanError(cause: unknown): string {
  const raw =
    cause instanceof Error
      ? cause.message
      : 'Something went wrong. Please try again.';
  if (raw === 'Internal Server Error' || raw === 'Failed to fetch')
    return 'We couldn’t complete that request. Please try again in a moment.';
  try {
    const parsed = JSON.parse(raw);
    return typeof parsed.detail === 'string'
      ? parsed.detail.replaceAll('_', ' ')
      : 'Please check your details and try again.';
  } catch {
    return raw;
  }
}

const IST = 'Asia/Kolkata';

export function formatDate(value: string) {
  return new Intl.DateTimeFormat('en-IN', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: IST,
  }).format(new Date(value));
}

export function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('en-IN', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: IST,
  }).format(new Date(value));
}

export function formatTime(value: string) {
  return new Intl.DateTimeFormat('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: IST,
  }).format(new Date(value));
}

export function timeAgo(value: string, now = Date.now()) {
  const minutes = Math.round((now - new Date(value).getTime()) / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return formatDate(value);
}

export function isToday(value: string) {
  const day = (date: Date) =>
    new Intl.DateTimeFormat('en-CA', { timeZone: IST }).format(date);
  return day(new Date(value)) === day(new Date());
}

const REASONS: Record<string, string> = {
  redflag_chest_pain: 'Chest pain',
  redflag_breathing: 'Breathing difficulty',
  redflag_unconscious: 'Fainting, fits or unresponsive',
  redflag_stroke: 'Possible stroke signs',
  redflag_bleeding: 'Heavy bleeding',
  redflag_poisoning: 'Possible poisoning or overdose',
  redflag_self_harm: 'Self-harm risk',
  unclear_symptoms: 'Couldn’t match a specialty',
  no_slots: 'No suitable slots available',
  too_many_reoffers: 'Slots kept filling up while booking',
};

/** Handoff reasons are stored as codes; the desk reads them in plain words. */
export function describeReason(reason: string) {
  return reason
    .split(',')
    .map((part) => {
      // "redflag_breathing:screen" = the patient answered yes on the safety questions.
      const [code, source] = part.trim().split(':');
      const label = REASONS[code] ?? code.replaceAll('_', ' ');
      if (source === 'screen') return `${label} (from safety questions)`;
      if (source === 'model')
        return `${label} (flagged by the assistant's safety check)`;
      return label;
    })
    .join(' · ');
}

const DOC_TYPES: Record<string, string> = {
  lab_report: 'Lab report',
  prescription: 'Prescription',
  discharge_summary: 'Discharge summary',
  imaging: 'Imaging report',
  other: 'Document',
};

export function describeDocType(type: string) {
  return DOC_TYPES[type] ?? type.replaceAll('_', ' ');
}
