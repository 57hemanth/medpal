import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  ArrowRight,
  CalendarDays,
  FileText,
  MapPin,
  MessageCircle,
  Pill,
  ShieldCheck,
  UploadCloud,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import type {
  Appointment,
  Consent,
  HealthRecord,
  PatientNotification,
} from '../../api/types';
import { useAuth } from '../../auth/AuthProvider';
import { RecordViewer } from '../records/RecordViewer';
import {
  Card,
  EmptyState,
  ErrorNotice,
  LoadingRows,
  PageHeader,
  StatusPill,
  describeDocType,
  formatDate,
  formatDateTime,
  humanError,
} from '../../components/ui';

function greeting() {
  const hour = Number(
    new Intl.DateTimeFormat('en-IN', {
      hour: 'numeric',
      hour12: false,
      timeZone: 'Asia/Kolkata',
    }).format(new Date()),
  );
  return hour < 12
    ? 'Good morning'
    : hour < 17
      ? 'Good afternoon'
      : 'Good evening';
}

function QuickAction({
  to,
  icon: Icon,
  title,
  description,
}: {
  to: string;
  icon: typeof MessageCircle;
  title: string;
  description: string;
}) {
  return (
    <Link
      to={to}
      className="card group flex items-start gap-3 p-4 hover:border-brand-200 hover:bg-brand-50/40"
    >
      <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-700">
        <Icon size={17} aria-hidden="true" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[13px] font-semibold">{title}</span>
        <span className="mt-0.5 block text-[12px] leading-relaxed text-muted">
          {description}
        </span>
      </span>
      <ArrowRight
        size={15}
        className="mt-1 text-subtle group-hover:text-brand-700"
        aria-hidden="true"
      />
    </Link>
  );
}

/** Home for patients and caregivers: what's next, what's new, who can see what. */
export function PatientHome() {
  const { auth } = useAuth();
  const caregiver = auth.role === 'caregiver';
  const [viewing, setViewing] = useState<{ id: string; title: string } | null>(
    null,
  );
  const appointments = useQuery({
    queryKey: ['appointments', 'upcoming', auth.user_id, auth.role],
    queryFn: () =>
      api<Appointment[]>('/api/appointments?when=upcoming&limit=5', {}, auth),
    enabled: !caregiver,
  });
  const records = useQuery({
    queryKey: ['records', auth.user_id, auth.role],
    queryFn: () => api<HealthRecord[]>('/api/records', {}, auth),
  });
  const consents = useQuery({
    queryKey: ['consents', auth.user_id, auth.role],
    queryFn: () => api<Consent[]>('/api/consents', {}, auth),
  });
  const notifications = useQuery({
    queryKey: ['notifications', auth.user_id, auth.role],
    queryFn: () => api<PatientNotification[]>('/api/notifications', {}, auth),
  });
  const unread = (notifications.data ?? []).filter((n) => !n.read_at);
  const next = appointments.data?.[0];
  // Patients see who can read THEIR record; caregivers see what was shared with them.
  const activeConsents = (consents.data ?? []).filter(
    (consent) =>
      !consent.revoked_at &&
      new Date(consent.expires_at) > new Date() &&
      (caregiver || consent.patient_id === auth.acting_for_patient_id),
  );
  const recent = [...(records.data ?? [])]
    .sort((a, b) => b.uploaded_at.localeCompare(a.uploaded_at))
    .slice(0, 5);

  return (
    <>
      <PageHeader
        eyebrow={caregiver ? 'Family care' : 'Home'}
        title={`${greeting()}, Asha`}
        description={
          caregiver
            ? 'You are viewing records that Lata Verma has shared with you.'
            : 'Find the right doctor, keep your reports in one place, and decide who can see them.'
        }
      />

      {unread.map((note) => (
        <div
          key={note.notification_id}
          role="status"
          className="mb-4 flex items-center gap-3 rounded-xl border border-brand-100 bg-brand-50 px-4 py-3 text-[14px] text-brand-900"
        >
          <Pill
            size={17}
            className="shrink-0 text-brand-700"
            aria-hidden="true"
          />
          <span className="flex-1">{note.body}</span>
          <Link
            to="/prescriptions"
            className="text-[13px] font-semibold text-brand-700"
          >
            View
          </Link>
          <button
            className="text-[12px] text-muted hover:text-ink"
            onClick={() =>
              void api(
                `/api/notifications/${note.notification_id}/read`,
                { method: 'POST' },
                auth,
              ).then(() => notifications.refetch())
            }
          >
            Dismiss
          </button>
        </div>
      ))}
      {!caregiver && (
        <div className="mb-6 grid gap-3 md:grid-cols-3">
          <QuickAction
            to="/care"
            icon={MessageCircle}
            title="Talk to the care assistant"
            description="Describe symptoms or ask about a report, in English or Hinglish."
          />
          <QuickAction
            to="/records"
            icon={UploadCloud}
            title="Add a report"
            description="Upload a lab report or prescription as a PDF."
          />
          <QuickAction
            to="/sharing"
            icon={ShieldCheck}
            title="Manage access"
            description="Share records with family, for a set time."
          />
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
        <div className="space-y-5">
          {!caregiver && (
            <Card
              title="Next appointment"
              action={
                <Link
                  to="/appointments"
                  className="text-[12px] font-semibold text-brand-700 hover:text-brand-900"
                >
                  All appointments
                </Link>
              }
            >
              {appointments.isPending ? (
                <LoadingRows rows={1} />
              ) : appointments.error ? (
                <ErrorNotice message={humanError(appointments.error)} />
              ) : next ? (
                <div className="flex flex-wrap items-center gap-4">
                  <div className="flex size-14 shrink-0 flex-col items-center justify-center rounded-xl border border-line bg-canvas">
                    <span className="text-[10px] font-semibold uppercase text-muted">
                      {new Intl.DateTimeFormat('en-IN', {
                        month: 'short',
                        timeZone: 'Asia/Kolkata',
                      }).format(new Date(next.starts_at))}
                    </span>
                    <span className="text-xl font-semibold leading-none">
                      {new Intl.DateTimeFormat('en-IN', {
                        day: 'numeric',
                        timeZone: 'Asia/Kolkata',
                      }).format(new Date(next.starts_at))}
                    </span>
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-[15px] font-semibold">
                      {next.doctor_name}
                    </p>
                    <p className="text-[13px] text-muted">
                      {next.specialty} · {formatDateTime(next.starts_at)}
                    </p>
                    <p className="mt-1 flex items-center gap-1 text-[12px] text-muted">
                      <MapPin size={12} aria-hidden="true" />
                      {next.clinic_name}, {next.city}
                    </p>
                  </div>
                  <StatusPill status={next.status} />
                </div>
              ) : (
                <EmptyState
                  icon={<CalendarDays size={18} />}
                  title="No upcoming appointments"
                  description="Tell the care assistant what's bothering you and it will find the right doctor."
                  action={
                    <Link to="/care" className="btn btn-primary">
                      Find care
                    </Link>
                  }
                />
              )}
            </Card>
          )}

          <Card
            title={caregiver ? 'Shared reports' : 'Recent reports'}
            action={
              <Link
                to="/records"
                className="text-[12px] font-semibold text-brand-700 hover:text-brand-900"
              >
                {caregiver ? 'Ask about these reports' : 'Open records'}
              </Link>
            }
            bodyClassName=""
          >
            {records.isPending ? (
              <LoadingRows />
            ) : records.error ? (
              <div className="p-5">
                <ErrorNotice message={humanError(records.error)} />
              </div>
            ) : recent.length ? (
              <ul className="divide-y divide-line">
                {recent.map((record) => (
                  <li
                    key={record.doc_id}
                    className="flex items-center gap-3 px-5 py-3"
                  >
                    <span className="flex size-8 items-center justify-center rounded-lg bg-canvas text-muted">
                      <FileText size={15} aria-hidden="true" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] font-medium">
                        {describeDocType(record.type)}
                      </span>
                      <span className="text-[12px] text-muted">
                        Added {formatDate(record.uploaded_at)}
                      </span>
                    </span>
                    <StatusPill status={record.status ?? 'ready'} />
                    <button
                      className="btn btn-secondary min-h-8 px-3 text-[12px]"
                      onClick={() =>
                        setViewing({
                          id: record.doc_id,
                          title: `${describeDocType(record.type)} · ${formatDate(record.uploaded_at)}`,
                        })
                      }
                    >
                      View
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                icon={<FileText size={18} />}
                title={caregiver ? 'Nothing shared yet' : 'No reports yet'}
                description={
                  caregiver
                    ? 'Reports appear here once the person you care for adds them.'
                    : 'Reports you add are only visible to you and the people you allow.'
                }
              />
            )}
          </Card>
        </div>

        <Card
          title={
            caregiver ? 'Access granted to you' : 'Who can see your records'
          }
          bodyClassName=""
        >
          {consents.isPending ? (
            <LoadingRows rows={2} />
          ) : consents.error ? (
            <div className="p-5">
              <ErrorNotice message={humanError(consents.error)} />
            </div>
          ) : activeConsents.length ? (
            <ul className="divide-y divide-line">
              {activeConsents.map((consent) => (
                <li key={consent.consent_id} className="px-5 py-3">
                  <p className="text-[13px] font-medium">
                    {caregiver
                      ? (consent.patient_name ?? 'Another patient')
                      : (consent.grantee_name ?? 'Care circle member')}
                  </p>
                  <p className="mt-0.5 text-[12px] text-muted">
                    {consent.purpose} · records until{' '}
                    {formatDate(consent.expires_at)}
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              icon={<ShieldCheck size={18} />}
              title="Only you"
              description="Nobody else can see your records. Your care team sees what they need for your visits."
            />
          )}
          <div className="border-t border-line px-5 py-3 text-[12px] text-muted">
            Every time someone opens a record, it&apos;s logged.{' '}
            <Link to="/sharing" className="font-semibold text-brand-700">
              Manage access
            </Link>
          </div>
        </Card>
      </div>
      {viewing && (
        <RecordViewer
          docId={viewing.id}
          title={viewing.title}
          onClose={() => setViewing(null)}
        />
      )}
    </>
  );
}
