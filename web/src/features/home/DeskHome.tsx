import { useQuery } from '@tanstack/react-query';
import {
  AlertTriangle,
  CalendarDays,
  ClipboardList,
  Clock3,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import type { Appointment, Handoff } from '../../api/types';
import { useAuth } from '../../auth/AuthProvider';
import {
  Card,
  EmptyState,
  ErrorNotice,
  LoadingRows,
  PageHeader,
  Stat,
  StatusPill,
  describeReason,
  formatTime,
  humanError,
  isToday,
  timeAgo,
} from '../../components/ui';

export function DeskHome() {
  const { auth } = useAuth();
  const handoffs = useQuery({
    queryKey: ['handoffs', auth.user_id],
    queryFn: () => api<Handoff[]>('/api/front-desk/handoffs', {}, auth),
    refetchInterval: 15_000,
  });
  const appointments = useQuery({
    queryKey: ['appointments', 'upcoming', auth.user_id, auth.role],
    queryFn: () =>
      api<Appointment[]>('/api/appointments?when=upcoming&limit=200', {}, auth),
  });
  const open = (handoffs.data ?? []).filter(
    (ticket) => ticket.status !== 'closed',
  );
  const emergencies = open.filter((ticket) => ticket.kind === 'emergency');
  const today = (appointments.data ?? []).filter((appt) =>
    isToday(appt.starts_at),
  );

  return (
    <>
      <PageHeader
        eyebrow="Overview"
        title="Clinic operations"
        description="Handoffs from the assistant, emergencies first, and today's bookings across the network."
        action={
          <Link to="/queue" className="btn btn-primary">
            <ClipboardList size={15} aria-hidden="true" />
            Open queue
          </Link>
        }
      />
      <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Open emergencies"
          value={handoffs.isPending ? '—' : emergencies.length}
          tone={emergencies.length ? 'red' : 'neutral'}
          icon={<AlertTriangle size={15} />}
          hint="Call back immediately"
        />
        <Stat
          label="Open handoffs"
          value={handoffs.isPending ? '—' : open.length}
          tone="amber"
          icon={<ClipboardList size={15} />}
        />
        <Stat
          label="Appointments today"
          value={appointments.isPending ? '—' : today.length}
          icon={<CalendarDays size={15} />}
        />
        <Stat
          label="Oldest open ticket"
          value={
            open.length
              ? timeAgo(
                  open.reduce(
                    (oldest, t) =>
                      t.created_at < oldest ? t.created_at : oldest,
                    open[0].created_at,
                  ),
                )
              : '—'
          }
          icon={<Clock3 size={15} />}
        />
      </div>
      <div className="grid gap-5 lg:grid-cols-2">
        <Card
          title="Needs attention"
          action={
            <Link
              to="/queue"
              className="text-[12px] font-semibold text-brand-700"
            >
              View all
            </Link>
          }
          bodyClassName=""
        >
          {handoffs.isPending ? (
            <LoadingRows />
          ) : handoffs.error ? (
            <div className="p-5">
              <ErrorNotice message={humanError(handoffs.error)} />
            </div>
          ) : open.length ? (
            <ul className="divide-y divide-line">
              {open.slice(0, 6).map((ticket) => (
                <li
                  key={ticket.ticket_id}
                  className="flex items-start gap-3 px-5 py-3"
                >
                  <StatusPill status={ticket.kind} />
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] font-medium">
                      {ticket.patient_name ?? 'Unknown patient'}
                    </span>
                    <span className="block truncate text-[12px] text-muted">
                      {describeReason(ticket.reason)}
                    </span>
                  </span>
                  <span className="whitespace-nowrap text-[12px] text-muted">
                    {timeAgo(ticket.created_at)}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              icon={<ClipboardList size={18} />}
              title="Queue is clear"
              description="New handoffs appear here within seconds."
            />
          )}
        </Card>
        <Card
          title="Today's appointments"
          action={
            <Link
              to="/appointments"
              className="text-[12px] font-semibold text-brand-700"
            >
              View all
            </Link>
          }
          bodyClassName=""
        >
          {appointments.isPending ? (
            <LoadingRows />
          ) : appointments.error ? (
            <div className="p-5">
              <ErrorNotice message={humanError(appointments.error)} />
            </div>
          ) : today.length ? (
            <ul className="divide-y divide-line">
              {today.slice(0, 6).map((appt) => (
                <li
                  key={appt.appt_id}
                  className="flex items-center gap-3 px-5 py-3"
                >
                  <span className="w-12 text-[13px] font-semibold">
                    {formatTime(appt.starts_at)}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-medium">
                      {appt.patient_name ?? 'Patient'}
                    </span>
                    <span className="block truncate text-[12px] text-muted">
                      {appt.doctor_name} · {appt.clinic_name}
                    </span>
                  </span>
                  <StatusPill status={appt.status} />
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              icon={<CalendarDays size={18} />}
              title="Nothing booked for today"
              description="Upcoming bookings are on the Appointments page."
            />
          )}
        </Card>
      </div>
    </>
  );
}
