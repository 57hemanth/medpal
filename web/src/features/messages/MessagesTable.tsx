import { Mail } from 'lucide-react';
import type { OutboxMessage } from '../../api/types';
import { EmptyState, StatusPill, formatDateTime } from '../../components/ui';

export const MESSAGE_KIND: Record<OutboxMessage['kind'], string> = {
  appointment_booked: 'Booking confirmation',
  appointment_cancelled: 'Cancellation notice',
  appointment_reminder_24h: 'Reminder, 1 day before',
  appointment_reminder_2h: 'Reminder, 2 hours before',
};

/** Why a message didn't go, in words a patient or front-desk member understands. */
function explain(message: OutboxMessage) {
  if (message.status === 'sent') return message.recipient ?? '';
  if (message.status === 'queued' && message.attempts > 0)
    return `Retrying: ${message.detail ?? 'delivery failed'}`;
  if (message.status === 'queued' || message.status === 'sending')
    return `Scheduled for ${formatDateTime(message.send_after)}`;
  const detail = message.detail ?? '';
  if (detail === 'created by the demo seed')
    return 'Booked before emails were on';
  return detail.charAt(0).toUpperCase() + detail.slice(1);
}

/** The appointment emails a person can see: their own, or everyone's for front desk and compliance. */
export function MessagesTable({
  messages,
  showPatient,
}: {
  messages: OutboxMessage[];
  showPatient: boolean;
}) {
  if (!messages.length)
    return (
      <EmptyState
        icon={<Mail size={18} />}
        title="No appointment emails yet"
        description="Booking confirmations, reminders a day and two hours before, and cancellation notices appear here."
      />
    );
  return (
    <div className="overflow-x-auto">
      <table className="table">
        <thead>
          <tr>
            <th>Message</th>
            {showPatient && <th>Patient</th>}
            <th className="hidden md:table-cell">Appointment</th>
            <th>Status</th>
            <th className="hidden lg:table-cell">Details</th>
          </tr>
        </thead>
        <tbody>
          {messages.map((message) => (
            <tr key={message.notification_id}>
              <td>
                <span className="block font-medium">
                  {MESSAGE_KIND[message.kind] ?? message.kind}
                </span>
                <span className="text-[12px] text-muted">
                  {message.sent_at
                    ? `Sent ${formatDateTime(message.sent_at)}`
                    : 'Email'}
                </span>
              </td>
              {showPatient && <td>{message.patient_name ?? '—'}</td>}
              <td className="hidden whitespace-nowrap text-muted md:table-cell">
                {message.starts_at ? formatDateTime(message.starts_at) : '—'}
                {message.doctor_name && (
                  <span className="block text-[12px]">
                    {message.doctor_name}
                  </span>
                )}
              </td>
              <td>
                <StatusPill status={message.status} />
              </td>
              <td className="hidden text-[12px] text-muted lg:table-cell">
                {explain(message)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
