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
    <div className="flex items-center gap-2.5">
      <span
        className={`flex size-9 items-center justify-center rounded-xl ${light ? 'bg-white/15 text-white' : 'bg-brand-700 text-white'}`}
      >
        <HeartPulse size={21} strokeWidth={1.8} aria-hidden="true" />
      </span>
      <span
        className={`text-[23px] font-bold tracking-[-0.06em] ${light ? 'text-white' : 'text-brand-900'}`}
      >
        MedPal
        <span className={light ? 'text-brand-200' : 'text-brand-500'}>.</span>
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
  variant?: 'primary' | 'secondary' | 'ghost';
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
        <LoaderCircle size={16} className="animate-spin" aria-hidden="true" />
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
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div>
        <p className="eyebrow mb-2.5">{eyebrow}</p>
        <h1 className="text-[28px] font-semibold leading-tight tracking-[-0.045em] sm:text-[34px]">
          {title}
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted sm:text-[15px]">
          {description}
        </p>
      </div>
      {action}
    </div>
  );
}

export function Badge({
  children,
  tone = 'neutral',
}: {
  children: ReactNode;
  tone?: 'neutral' | 'green' | 'amber' | 'red';
}) {
  const tones = {
    neutral: 'border-line bg-slate-50 text-slate-600',
    green: 'border-brand-100 bg-brand-50 text-brand-700',
    amber: 'border-amber-200 bg-amber-50 text-amber-800',
    red: 'border-red-200 bg-red-50 text-red-700',
  };
  return <span className={`badge ${tones[tone]}`}>{children}</span>;
}

export function ErrorNotice({ message }: { message?: string | null }) {
  if (!message) return null;
  return (
    <div
      role="alert"
      className="flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800"
    >
      <AlertCircle className="mt-0.5 shrink-0" size={17} aria-hidden="true" />
      <p className="min-w-0 break-words leading-relaxed">{message}</p>
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  description,
}: {
  icon: ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      <div
        className="mb-4 flex size-12 items-center justify-center rounded-2xl bg-brand-50 text-brand-700"
        aria-hidden="true"
      >
        {icon}
      </div>
      <h3 className="text-sm font-semibold">{title}</h3>
      <p className="mt-2 max-w-xs text-sm leading-relaxed text-muted">
        {description}
      </p>
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
        size={15}
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
      className="inline-flex min-h-11 items-center gap-1 text-sm font-semibold text-brand-700 hover:text-brand-900"
      {...props}
    >
      {children}
      <ArrowUpRight size={15} aria-hidden="true" />
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

export function formatDate(value: string) {
  return new Intl.DateTimeFormat('en-IN', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'Asia/Kolkata',
  }).format(new Date(value));
}
