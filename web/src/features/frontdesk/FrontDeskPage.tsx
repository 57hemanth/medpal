import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  ArrowRight,
  Check,
  CircleCheck,
  ClipboardList,
  Clock3,
  Search,
  Siren,
} from 'lucide-react';
import { api } from '../../api/client';
import type { Handoff } from '../../api/types';
import { useAuth } from '../../auth/AuthProvider';
import {
  Badge,
  Button,
  EmptyState,
  ErrorNotice,
  PageHeader,
  StatusPill,
  formatDate,
  describeReason,
  timeAgo,
  humanError,
} from '../../components/ui';

const filters = [
  { id: 'all', label: 'All requests' },
  { id: 'open', label: 'Open' },
  { id: 'in_progress', label: 'In progress' },
  { id: 'closed', label: 'Closed' },
];
export function FrontDeskPage() {
  const { auth } = useAuth();
  const [filter, setFilter] = useState('open');
  const [search, setSearch] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState<string | null>(null);
  const {
    data = [],
    refetch,
    isPending,
    error: queryError,
  } = useQuery({
    queryKey: ['handoffs', auth.user_id],
    queryFn: () => api<Handoff[]>('/api/front-desk/handoffs', {}, auth),
    retry: false,
  });
  async function update(id: string, status: string) {
    setPending(id);
    setError('');
    try {
      await api(
        `/api/front-desk/handoffs/${id}/status`,
        { method: 'POST', body: JSON.stringify({ status }) },
        auth,
      );
      await refetch();
    } catch (cause) {
      setError(humanError(cause));
    } finally {
      setPending(null);
    }
  }
  const visible = data.filter(
    (handoff) =>
      (filter === 'all' || handoff.status === filter) &&
      `${handoff.kind} ${describeReason(handoff.reason)} ${handoff.patient_name ?? ''} ${handoff.ticket_id}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  return (
    <section>
      <PageHeader
        eyebrow="Operations"
        title="Handoff queue"
        description="Requests the assistant handed to a person: emergencies first, then unclear requests and records questions."
        action={
          <Button
            variant="secondary"
            busy={isPending}
            onClick={() => void refetch()}
          >
            Refresh queue
          </Button>
        }
      />
      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        {[
          {
            label: 'Open requests',
            value: data.filter((item) => item.status === 'open').length,
            icon: ClipboardList,
          },
          {
            label: 'In progress',
            value: data.filter((item) => item.status === 'in_progress').length,
            icon: Clock3,
          },
          {
            label: 'Closed requests',
            value: data.filter((item) => item.status === 'closed').length,
            icon: CircleCheck,
          },
        ].map(({ label, value, icon: Icon }) => (
          <div key={label} className="panel flex items-center gap-4 p-5">
            <span className="flex size-11 items-center justify-center rounded-xl bg-brand-50 text-brand-700">
              <Icon size={21} />
            </span>
            <div>
              <p className="text-xs text-muted">{label}</p>
              <p className="mt-1 text-2xl font-semibold tracking-tight">
                {isPending ? '—' : value}
              </p>
            </div>
          </div>
        ))}
      </div>
      <div className="mb-5">
        <ErrorNotice
          message={error || (queryError ? humanError(queryError) : '')}
        />
      </div>
      <div className="panel overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-line px-5 py-4">
          <div
            className="flex flex-wrap gap-1"
            role="group"
            aria-label="Filter request status"
          >
            {filters.map(({ id, label }) => (
              <button
                key={id}
                onClick={() => setFilter(id)}
                aria-pressed={filter === id}
                className={`min-h-11 rounded-lg px-3 text-xs font-medium ${filter === id ? 'bg-brand-50 text-brand-800' : 'text-muted hover:bg-canvas'}`}
              >
                {label}
              </button>
            ))}
          </div>
          <label className="flex min-h-11 items-center gap-2 rounded-xl border border-line px-3">
            <Search size={15} className="text-muted" />
            <span className="sr-only">Search requests</span>
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search requests…"
              className="w-40 bg-transparent py-2 text-sm placeholder:text-muted sm:text-xs"
            />
          </label>
        </div>
        {isPending ? (
          <p role="status" className="p-8 text-sm text-muted">
            Loading the clinic queue…
          </p>
        ) : visible.length === 0 ? (
          <EmptyState
            icon={<ClipboardList size={24} />}
            title={search ? 'No matching requests' : 'A clear queue.'}
            description={
              search
                ? 'Try another search or change your status filter.'
                : 'Requests that need a personal follow-up will appear here.'
            }
          />
        ) : (
          <div className="divide-y divide-line">
            {visible.map((handoff) => (
              <article
                key={handoff.ticket_id}
                className="flex flex-wrap items-start gap-4 p-5 sm:items-center sm:px-6"
              >
                <span
                  className={`flex size-11 shrink-0 items-center justify-center rounded-xl ${handoff.kind === 'emergency' ? 'bg-red-50 text-red-700' : 'bg-brand-50 text-brand-700'}`}
                >
                  {handoff.kind === 'emergency' ? (
                    <Siren size={20} />
                  ) : (
                    <ClipboardList size={20} />
                  )}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-sm font-semibold">
                      {handoff.patient_name ?? 'Unknown patient'}
                      <span className="ml-2 font-normal text-muted">
                        {handoff.kind === 'emergency'
                          ? 'Urgent care handoff'
                          : 'Care coordination request'}
                      </span>
                    </h2>
                    <StatusPill status={handoff.status} />
                  </div>
                  <p className="mt-1.5 text-xs leading-relaxed text-muted">
                    {describeReason(handoff.reason)}
                  </p>
                  <p className="mt-2 text-[11px] text-muted">
                    {timeAgo(handoff.created_at)} · Ref{' '}
                    {handoff.ticket_id.slice(0, 8)}
                  </p>
                </div>
                {handoff.status !== 'closed' && (
                  <Button
                    variant="secondary"
                    busy={pending === handoff.ticket_id}
                    disabled={!!pending}
                    className="text-xs"
                    onClick={() =>
                      void update(
                        handoff.ticket_id,
                        handoff.status === 'open' ? 'in_progress' : 'closed',
                      )
                    }
                  >
                    {handoff.status === 'open' ? (
                      <>
                        Pick up request
                        <ArrowRight size={14} />
                      </>
                    ) : (
                      <>
                        <Check size={14} />
                        Mark complete
                      </>
                    )}
                  </Button>
                )}
              </article>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
