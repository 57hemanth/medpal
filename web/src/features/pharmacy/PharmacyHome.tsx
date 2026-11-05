import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, ClipboardList, PackageX, Pill } from 'lucide-react';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import type { QueueItem, StockRow } from '../../api/types';
import { useAuth } from '../../auth/AuthProvider';
import {
  Button,
  Card,
  EmptyState,
  ErrorNotice,
  LoadingRows,
  PageHeader,
  Segmented,
  Stat,
  StatusPill,
  formatDateTime,
  humanError,
  timeAgo,
} from '../../components/ui';

type Filter = 'reserved' | 'dispensed' | 'all';

/** Pharmacist home: who is waiting to collect, and what needs restocking at this clinic. */
export function PharmacyHome() {
  const { auth } = useAuth();
  const client = useQueryClient();
  const [filter, setFilter] = useState<Filter>('reserved');
  const clinic = useQuery({
    queryKey: ['pharmacy-me', auth.user_id],
    queryFn: () =>
      api<{ name: string; city: string }>('/api/pharmacy/me', {}, auth),
  });
  const queue = useQuery({
    queryKey: ['pharmacy-queue', auth.user_id],
    queryFn: () =>
      api<QueueItem[]>('/api/pharmacy/queue?status_filter=all', {}, auth),
    refetchInterval: 15_000,
  });
  const stock = useQuery({
    queryKey: ['pharmacy-stock', auth.user_id],
    queryFn: () => api<StockRow[]>('/api/pharmacy/stock', {}, auth),
  });
  const act = useMutation({
    mutationFn: ({
      id,
      action,
    }: {
      id: string;
      action: 'dispense' | 'release';
    }) => api(`/api/pharmacy/queue/${id}/${action}`, { method: 'POST' }, auth),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['pharmacy-queue'] });
      void client.invalidateQueries({ queryKey: ['pharmacy-stock'] });
    },
  });
  const rows = stock.data ?? [];
  const out = rows.filter((r) => r.status === 'out_of_stock');
  const low = rows.filter((r) => r.status === 'low');
  const unmet = rows.reduce((sum, r) => sum + r.unmet, 0);
  const waiting = (queue.data ?? []).filter((q) => q.status === 'reserved');
  const shown = (queue.data ?? []).filter(
    (q) => filter === 'all' || q.status === filter,
  );

  return (
    <>
      <PageHeader
        eyebrow="Pharmacy"
        title={clinic.data ? `${clinic.data.name} pharmacy` : 'Pharmacy'}
        description="Prescriptions are held here automatically when a doctor signs. Hand them over, and the patient is told their medicines are ready."
        action={
          <Link to="/stock" className="btn btn-secondary">
            Stock &amp; restock
          </Link>
        }
      />
      <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Waiting to collect"
          value={queue.isPending ? '—' : waiting.length}
          icon={<ClipboardList size={15} />}
        />
        <Stat
          label="Out of stock"
          value={stock.isPending ? '—' : out.length}
          tone={out.length ? 'red' : 'neutral'}
          icon={<PackageX size={15} />}
        />
        <Stat
          label="Running low"
          value={stock.isPending ? '—' : low.length}
          tone={low.length ? 'amber' : 'neutral'}
          icon={<Pill size={15} />}
          hint="10 packs or fewer available"
        />
        <Stat
          label="Prescriptions not held (30 days)"
          value={stock.isPending ? '—' : unmet}
          tone={unmet ? 'red' : 'neutral'}
          icon={<AlertTriangle size={15} />}
          hint="Signed while out of stock"
        />
      </div>
      <Card
        title="Dispensing queue"
        action={
          <Segmented
            label="Show"
            value={filter}
            onChange={setFilter}
            options={[
              { value: 'reserved', label: 'Waiting' },
              { value: 'dispensed', label: 'Collected' },
              { value: 'all', label: 'All' },
            ]}
          />
        }
        bodyClassName=""
      >
        {act.error && (
          <div className="px-5 pt-4">
            <ErrorNotice message={humanError(act.error)} />
          </div>
        )}
        {queue.isPending ? (
          <LoadingRows />
        ) : queue.error ? (
          <div className="p-5">
            <ErrorNotice message={humanError(queue.error)} />
          </div>
        ) : shown.length ? (
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>Patient</th>
                  <th>Medicine</th>
                  <th className="hidden md:table-cell">Prescribed by</th>
                  <th>Held</th>
                  <th>Status</th>
                  <th>
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {shown.map((item) => (
                  <tr key={item.reservation_id}>
                    <td className="font-medium">{item.patient_name ?? '—'}</td>
                    <td>
                      <span className="block">{item.medicine}</span>
                      <span className="text-[12px] text-muted">
                        {item.pack_size ?? 'one pack'}
                      </span>
                    </td>
                    <td className="hidden text-muted md:table-cell">
                      {item.doctor_name ?? '—'}
                    </td>
                    <td
                      className="whitespace-nowrap text-muted"
                      title={formatDateTime(item.reserved_at)}
                    >
                      {timeAgo(item.reserved_at)}
                    </td>
                    <td>
                      <StatusPill status={item.status} />
                    </td>
                    <td className="whitespace-nowrap text-right">
                      {item.status === 'reserved' && (
                        <span className="inline-flex gap-1.5">
                          <Button
                            busy={
                              act.isPending &&
                              act.variables?.id === item.reservation_id &&
                              act.variables.action === 'dispense'
                            }
                            onClick={() =>
                              act.mutate({
                                id: item.reservation_id,
                                action: 'dispense',
                              })
                            }
                          >
                            Hand over
                          </Button>
                          <Button
                            variant="ghost"
                            onClick={() =>
                              act.mutate({
                                id: item.reservation_id,
                                action: 'release',
                              })
                            }
                          >
                            Release
                          </Button>
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            icon={<ClipboardList size={18} />}
            title={
              filter === 'reserved' ? 'Nobody waiting' : 'Nothing here yet'
            }
            description="When a doctor signs a note with medicines in stock here, they're held for the patient and appear in this queue."
          />
        )}
      </Card>
    </>
  );
}
