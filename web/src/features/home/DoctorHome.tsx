import { useQuery } from '@tanstack/react-query';
import {
  CalendarDays,
  CheckCircle2,
  ClipboardPen,
  NotebookPen,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import type { Consultation } from '../../api/types';
import { useAuth } from '../../auth/AuthProvider';
import {
  Avatar,
  Badge,
  Card,
  EmptyState,
  ErrorNotice,
  LoadingRows,
  PageHeader,
  Stat,
  formatDateTime,
  formatTime,
  humanError,
  isToday,
} from '../../components/ui';

function noteState(item: Consultation) {
  if (item.signed) return <Badge tone="green">Signed</Badge>;
  if (item.encounter_id) return <Badge tone="amber">Awaiting signature</Badge>;
  return <Badge>Not started</Badge>;
}

export function DoctorHome() {
  const { auth } = useAuth();
  const {
    data = [],
    isPending,
    error,
  } = useQuery({
    queryKey: ['consultations', auth.user_id],
    queryFn: () => api<Consultation[]>('/api/scribe/consultations', {}, auth),
  });
  const upcoming = data
    .filter(
      (item) => new Date(item.starts_at).getTime() > Date.now() - 12 * 3600_000,
    )
    .sort((a, b) => a.starts_at.localeCompare(b.starts_at));
  const today = upcoming.filter((item) => isToday(item.starts_at));
  const awaiting = data.filter((item) => item.encounter_id && !item.signed);
  const signed = data.filter((item) => item.signed);

  return (
    <>
      <PageHeader
        eyebrow="Today"
        title="Your clinic day"
        description="Start a consultation, review the drafted note, and sign. Nothing is saved to the record until you sign."
        action={
          <Link to="/consultations" className="btn btn-primary">
            <NotebookPen size={15} aria-hidden="true" />
            Open consultations
          </Link>
        }
      />
      <div className="mb-6 grid gap-3 sm:grid-cols-3">
        <Stat
          label="Consultations today"
          value={isPending ? '—' : today.length}
          icon={<CalendarDays size={15} />}
        />
        <Stat
          label="Notes awaiting signature"
          value={isPending ? '—' : awaiting.length}
          tone={awaiting.length ? 'amber' : 'neutral'}
          icon={<ClipboardPen size={15} />}
          hint="Drafts are never part of the record until signed"
        />
        <Stat
          label="Signed notes"
          value={isPending ? '—' : signed.length}
          tone="green"
          icon={<CheckCircle2 size={15} />}
        />
      </div>
      <Card title="Upcoming consultations" bodyClassName="">
        {isPending ? (
          <LoadingRows />
        ) : error ? (
          <div className="p-5">
            <ErrorNotice message={humanError(error)} />
          </div>
        ) : upcoming.length ? (
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Patient</th>
                  <th className="hidden sm:table-cell">Clinic</th>
                  <th>Note</th>
                  <th>
                    <span className="sr-only">Action</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {upcoming.slice(0, 12).map((item) => (
                  <tr key={item.appt_id}>
                    <td className="whitespace-nowrap font-medium">
                      {isToday(item.starts_at)
                        ? `Today ${formatTime(item.starts_at)}`
                        : formatDateTime(item.starts_at)}
                    </td>
                    <td>
                      <span className="flex items-center gap-2.5">
                        <Avatar
                          name={item.patient_name ?? 'Patient'}
                          size={26}
                        />
                        {item.patient_name ?? 'Patient'}
                      </span>
                    </td>
                    <td className="hidden text-muted sm:table-cell">
                      {item.clinic_name}
                    </td>
                    <td>{noteState(item)}</td>
                    <td className="text-right">
                      <Link
                        to="/consultations"
                        className="text-[12px] font-semibold text-brand-700 hover:text-brand-900"
                      >
                        {item.signed ? 'View' : 'Open'}
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            icon={<CalendarDays size={18} />}
            title="No upcoming consultations"
            description="Appointments booked with you will appear here."
          />
        )}
      </Card>
    </>
  );
}
