import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CalendarDays, Mail, MessageCircle } from 'lucide-react';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import type { Appointment, ContactSettings } from '../../api/types';
import { useAuth } from '../../auth/AuthProvider';
import {
  Avatar,
  Button,
  Card,
  EmptyState,
  ErrorNotice,
  LoadingRows,
  PageHeader,
  Segmented,
  StatusPill,
  formatDateTime,
  humanError,
} from '../../components/ui';

type When = 'upcoming' | 'past' | 'all';

/** Patients see their own appointments; the front desk sees the network's. RLS decides which rows. */
export function AppointmentsPage() {
  const { auth } = useAuth();
  const desk = auth.role === 'desk';
  const client = useQueryClient();
  const [when, setWhen] = useState<When>('upcoming');
  const [query, setQuery] = useState('');
  const [confirming, setConfirming] = useState<string | null>(null);
  const {
    data = [],
    isPending,
    error,
  } = useQuery({
    queryKey: ['appointments', when, auth.user_id, auth.role],
    queryFn: () =>
      api<Appointment[]>(`/api/appointments?when=${when}&limit=200`, {}, auth),
  });
  const patient = auth.role === 'patient';
  const contact = useQuery({
    queryKey: ['contact', auth.user_id],
    queryFn: () => api<ContactSettings>('/api/me/contact', {}, auth),
    enabled: patient,
  });
  const remindersOff =
    patient &&
    !!contact.data &&
    !(contact.data.email_verified && contact.data.email_notifications);
  const cancel = useMutation({
    mutationFn: (apptId: string) =>
      api(`/api/appointments/${apptId}/cancel`, { method: 'POST' }, auth),
    onSuccess: () => {
      setConfirming(null);
      void client.invalidateQueries({ queryKey: ['appointments'] });
    },
  });
  const needle = query.trim().toLowerCase();
  const rows = needle
    ? data.filter((appt) =>
        [appt.patient_name, appt.doctor_name, appt.specialty, appt.clinic_name]
          .join(' ')
          .toLowerCase()
          .includes(needle),
      )
    : data;

  return (
    <>
      <PageHeader
        eyebrow={desk ? 'Operations' : 'Care'}
        title="Appointments"
        description={
          desk
            ? 'Bookings across all clinics. Cancelling frees the slot and is recorded in the audit log.'
            : 'Your visits. Cancel one you can no longer make so someone else can take the slot.'
        }
        action={
          !desk && (
            <Link to="/care" className="btn btn-primary">
              <MessageCircle size={15} aria-hidden="true" />
              Book a visit
            </Link>
          )
        }
      />
      {remindersOff && (
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-brand-100 bg-brand-50 px-4 py-3 text-[13px] text-brand-900">
          <span className="flex items-center gap-2">
            <Mail size={15} aria-hidden="true" />
            {contact.data?.email && !contact.data.email_verified
              ? 'Confirm your email to get booking confirmations and reminders.'
              : 'Get a reminder by email the day before and two hours before each visit.'}
          </span>
          <Link to="/settings" className="font-semibold underline">
            Email settings
          </Link>
        </div>
      )}
      <Card bodyClassName="">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
          <Segmented
            label="Show appointments"
            value={when}
            onChange={setWhen}
            options={[
              { value: 'upcoming', label: 'Upcoming' },
              { value: 'past', label: 'Past' },
              { value: 'all', label: 'All' },
            ]}
          />
          {desk && (
            <label className="w-full sm:w-72">
              <span className="sr-only">Search appointments</span>
              <input
                className="field py-2"
                placeholder="Search patient, doctor, clinic…"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </label>
          )}
        </div>
        {cancel.error && (
          <div className="px-4 pt-4">
            <ErrorNotice message={humanError(cancel.error)} />
          </div>
        )}
        {isPending ? (
          <LoadingRows rows={5} />
        ) : error ? (
          <div className="p-5">
            <ErrorNotice message={humanError(error)} />
          </div>
        ) : rows.length ? (
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>When</th>
                  {desk && <th>Patient</th>}
                  <th>Doctor</th>
                  <th className="hidden md:table-cell">Clinic</th>
                  <th>Status</th>
                  <th>
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((appt) => {
                  const cancellable =
                    appt.status === 'booked' &&
                    new Date(appt.starts_at) > new Date();
                  return (
                    <tr key={appt.appt_id}>
                      <td className="whitespace-nowrap font-medium">
                        {formatDateTime(appt.starts_at)}
                      </td>
                      {desk && <td>{appt.patient_name ?? '—'}</td>}
                      <td>
                        <span className="flex items-center gap-2.5">
                          <Avatar name={appt.doctor_name} size={26} />
                          <span>
                            <span className="block">{appt.doctor_name}</span>
                            <span className="block text-[12px] text-muted">
                              {appt.specialty}
                            </span>
                          </span>
                        </span>
                      </td>
                      <td className="hidden text-muted md:table-cell">
                        {appt.clinic_name}, {appt.city}
                      </td>
                      <td>
                        <StatusPill status={appt.status} />
                      </td>
                      <td className="whitespace-nowrap text-right">
                        {cancellable &&
                          (confirming === appt.appt_id ? (
                            <span className="inline-flex gap-1.5">
                              <Button
                                variant="danger"
                                busy={cancel.isPending}
                                onClick={() => cancel.mutate(appt.appt_id)}
                              >
                                Confirm cancel
                              </Button>
                              <Button
                                variant="ghost"
                                onClick={() => setConfirming(null)}
                              >
                                Keep
                              </Button>
                            </span>
                          ) : (
                            <Button
                              variant="secondary"
                              onClick={() => setConfirming(appt.appt_id)}
                            >
                              Cancel
                            </Button>
                          ))}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            icon={<CalendarDays size={18} />}
            title={
              needle
                ? 'No matches'
                : `No ${when === 'all' ? '' : when} appointments`
            }
            description={
              desk
                ? 'Try another filter or search.'
                : 'The care assistant can find you a doctor and book a slot.'
            }
          />
        )}
      </Card>
    </>
  );
}
