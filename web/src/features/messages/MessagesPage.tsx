import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import type { OutboxMessage } from '../../api/types';
import { useAuth } from '../../auth/AuthProvider';
import {
  Card,
  ErrorNotice,
  LoadingRows,
  PageHeader,
  Segmented,
  Stat,
  humanError,
} from '../../components/ui';
import { MessagesTable } from './MessagesTable';

type Filter = 'all' | 'scheduled' | 'sent' | 'problems';

const matches: Record<Filter, (m: OutboxMessage) => boolean> = {
  all: () => true,
  scheduled: (m) => m.status === 'queued' || m.status === 'sending',
  sent: (m) => m.status === 'sent',
  problems: (m) =>
    m.status === 'failed' ||
    m.status === 'skipped' ||
    (m.status === 'queued' && m.attempts > 0),
};

/** Front desk and compliance: every appointment email, scheduled or sent, and why any didn't go. */
export function MessagesPage() {
  const { auth } = useAuth();
  const [filter, setFilter] = useState<Filter>('all');
  const {
    data = [],
    isPending,
    error,
  } = useQuery({
    queryKey: ['messages', auth.user_id, auth.role],
    queryFn: () => api<OutboxMessage[]>('/api/messages', {}, auth),
    refetchInterval: 15_000,
  });
  const count = (f: Filter) => data.filter(matches[f]).length;
  return (
    <>
      <PageHeader
        eyebrow="Operations"
        title="Patient messages"
        description="Appointment emails: confirmations, reminders a day and two hours before, and cancellations. Only patients who confirmed their address are emailed."
      />
      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        <Stat label="Scheduled" value={count('scheduled')} />
        <Stat label="Sent" value={count('sent')} />
        <Stat
          label="Not sent or failing"
          value={count('problems')}
          hint="No confirmed address, emails turned off, or delivery failed"
        />
      </div>
      <Card
        bodyClassName=""
        title="Emails"
        action={
          <Segmented
            label="Filter emails"
            value={filter}
            onChange={setFilter}
            options={[
              { value: 'all', label: 'All' },
              { value: 'scheduled', label: 'Scheduled' },
              { value: 'sent', label: 'Sent' },
              { value: 'problems', label: 'Not sent' },
            ]}
          />
        }
      >
        {isPending ? (
          <LoadingRows rows={5} />
        ) : error ? (
          <div className="p-5">
            <ErrorNotice message={humanError(error)} />
          </div>
        ) : (
          <MessagesTable messages={data.filter(matches[filter])} showPatient />
        )}
      </Card>
    </>
  );
}
