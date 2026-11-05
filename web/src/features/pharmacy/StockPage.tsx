import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Package } from 'lucide-react';
import { api } from '../../api/client';
import type { StockRow } from '../../api/types';
import { useAuth } from '../../auth/AuthProvider';
import {
  Card,
  EmptyState,
  ErrorNotice,
  LoadingRows,
  PageHeader,
  Segmented,
  StatusPill,
  humanError,
  timeAgo,
} from '../../components/ui';

/** Stock at the pharmacist's clinic, with what needs reordering first. Counts come from the pharmacy feed. */
export function StockPage() {
  const { auth } = useAuth();
  const [view, setView] = useState<'action' | 'all'>('action');
  const {
    data = [],
    isPending,
    error,
  } = useQuery({
    queryKey: ['pharmacy-stock', auth.user_id],
    queryFn: () => api<StockRow[]>('/api/pharmacy/stock', {}, auth),
  });
  const rows =
    view === 'action' ? data.filter((r) => r.status !== 'in_stock') : data;

  return (
    <>
      <PageHeader
        eyebrow="Pharmacy"
        title="Stock & restock"
        description="Counts come from the pharmacy system's feed; MedPal adds what doctors have reserved and prescribed. Reorder from the top: medicines prescribed but not held come first."
      />
      <Card
        bodyClassName=""
        title={
          view === 'action' ? 'Needs restocking or a recount' : 'All medicines'
        }
        action={
          <Segmented
            label="Show"
            value={view}
            onChange={setView}
            options={[
              { value: 'action', label: 'Needs action' },
              { value: 'all', label: 'All' },
            ]}
          />
        }
      >
        {isPending ? (
          <LoadingRows rows={6} />
        ) : error ? (
          <div className="p-5">
            <ErrorNotice message={humanError(error)} />
          </div>
        ) : rows.length ? (
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>Medicine</th>
                  <th className="hidden lg:table-cell">Class</th>
                  <th className="text-right">Available</th>
                  <th className="text-right">Held</th>
                  <th className="text-right">Count</th>
                  <th className="text-right">Prescribed (30 d)</th>
                  <th className="text-right">Not held</th>
                  <th>Counted</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.medicine_id}>
                    <td>
                      <span className="block font-medium">{r.name}</span>
                      <span className="text-[12px] text-muted">
                        {r.composition}
                      </span>
                    </td>
                    <td className="hidden text-muted lg:table-cell">
                      {r.therapeutic_class ?? '—'}
                    </td>
                    <td className="text-right font-semibold">{r.available}</td>
                    <td className="text-right">{r.reserved}</td>
                    <td className="text-right text-muted">{r.qty ?? '—'}</td>
                    <td className="text-right">{r.demand}</td>
                    <td
                      className={`text-right ${r.unmet ? 'font-semibold text-red-700' : 'text-muted'}`}
                    >
                      {r.unmet}
                    </td>
                    <td className="whitespace-nowrap text-muted">
                      {r.as_of ? timeAgo(r.as_of) : 'never'}
                    </td>
                    <td>
                      <StatusPill status={r.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            icon={<Package size={18} />}
            title="Nothing needs action"
            description="Every medicine is in stock with a recent count."
          />
        )}
        <p className="border-t border-line px-5 py-3 text-[12px] text-muted">
          Available = count − held for patients. Low = 10 packs or fewer. A
          count older than 48 hours is shown as old, never as fact.
        </p>
      </Card>
    </>
  );
}
