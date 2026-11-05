import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Package, SlidersHorizontal } from 'lucide-react';
import { api } from '../../api/client';
import type { StockAdjustment, StockRow } from '../../api/types';
import { useAuth } from '../../auth/AuthProvider';
import {
  Card,
  Modal,
  formatDateTime,
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
const KINDS = {
  count: {
    label: 'Count',
    help: 'Packs on the shelf now',
    verb: 'Counted',
  },
  delivery: { label: 'Delivery', help: 'Packs received', verb: 'Received' },
  write_off: {
    label: 'Write off',
    help: 'Packs expired, damaged or lost',
    verb: 'Wrote off',
  },
} as const;
type Kind = keyof typeof KINDS;

/** Count, receive or write off one medicine. Every change needs a reason and is logged. */
function AdjustStock({ row, onClose }: { row: StockRow; onClose: () => void }) {
  const { auth } = useAuth();
  const client = useQueryClient();
  const [kind, setKind] = useState<Kind>('count');
  const [qty, setQty] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const current = row.qty ?? 0;
  const amount = Number(qty);
  const valid = qty !== '' && Number.isInteger(amount) && amount >= 0;
  const after = !valid
    ? null
    : kind === 'count'
      ? amount
      : kind === 'delivery'
        ? current + amount
        : current - amount;
  async function save() {
    if (!valid || !reason.trim()) {
      setError('Enter a whole number of packs and a reason.');
      return;
    }
    if (after !== null && after < 0) {
      setError(`Only ${current} on hand; you can't write off more.`);
      return;
    }
    setBusy(true);
    setError('');
    try {
      await api(
        `/api/pharmacy/stock/${row.medicine_id}`,
        {
          method: 'POST',
          body: JSON.stringify({ kind, qty: amount, reason: reason.trim() }),
        },
        auth,
      );
      await client.invalidateQueries({ queryKey: ['pharmacy-stock'] });
      await client.invalidateQueries({ queryKey: ['stock-history'] });
      onClose();
    } catch (cause) {
      setError(humanError(cause));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={`Update stock: ${row.name}`}
      description={`On hand now: ${row.qty ?? 'never counted'}${row.reserved ? ` · ${row.reserved} held for patients` : ''}`}
      onClose={onClose}
      onSubmit={save}
      submitLabel="Save change"
      busy={busy}
      error={error}
    >
      <Segmented
        label="Change"
        value={kind}
        onChange={setKind}
        options={(Object.keys(KINDS) as Kind[]).map((value) => ({
          value,
          label: KINDS[value].label,
        }))}
      />
      <label className="block">
        <span className="field-label">{KINDS[kind].help}</span>
        <input
          className="field"
          type="number"
          inputMode="numeric"
          min={0}
          step={1}
          value={qty}
          onChange={(event) => setQty(event.target.value)}
        />
      </label>
      {after !== null && (
        <p className="text-[13px] text-muted">
          On hand after this:{' '}
          <span
            className={`font-semibold ${after < 0 ? 'text-red-700' : 'text-ink'}`}
          >
            {current} → {after}
          </span>
        </p>
      )}
      <label className="block">
        <span className="field-label">Reason</span>
        <input
          className="field"
          maxLength={300}
          placeholder={
            kind === 'delivery'
              ? 'e.g. Invoice 4521 from distributor'
              : kind === 'write_off'
                ? 'e.g. Expired batch B12'
                : 'e.g. Weekly shelf count'
          }
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </label>
      <p className="text-[12px] text-muted">
        The next reading from the pharmacy system's feed replaces this count.
      </p>
    </Modal>
  );
}

function StockHistory() {
  const { auth } = useAuth();
  const { data = [] } = useQuery({
    queryKey: ['stock-history', auth.user_id],
    queryFn: () =>
      api<StockAdjustment[]>('/api/pharmacy/stock/history', {}, auth),
  });
  if (!data.length) return null;
  return (
    <Card title="Recent stock changes" className="mt-6" bodyClassName="">
      <ul className="divide-y divide-line">
        {data.slice(0, 15).map((change) => (
          <li
            key={change.adjustment_id}
            className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-5 py-3 text-[13px]"
          >
            <span>
              <span className="font-medium">{change.medicine}</span>
              <span className="text-muted">
                {' '}
                · {KINDS[change.kind].verb} · {change.qty_before} →{' '}
                {change.qty_after} · {change.reason}
              </span>
            </span>
            <span className="text-[12px] text-muted">
              {formatDateTime(change.made_at)}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export function StockPage() {
  const { auth } = useAuth();
  const [view, setView] = useState<'action' | 'all'>('action');
  const [editing, setEditing] = useState<StockRow | null>(null);
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
        description="Counts come from the pharmacy system's feed, or from your own counts and deliveries. MedPal adds what doctors have reserved and prescribed. Reorder from the top: medicines prescribed but not held come first."
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
                  <th>
                    <span className="sr-only">Actions</span>
                  </th>
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
                    <td className="text-right">
                      <button
                        type="button"
                        className="btn btn-ghost px-2.5 text-xs"
                        aria-label={`Update stock of ${r.name}`}
                        onClick={() => setEditing(r)}
                      >
                        <SlidersHorizontal size={14} />
                        Update
                      </button>
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
      <StockHistory />
      {editing && (
        <AdjustStock row={editing} onClose={() => setEditing(null)} />
      )}
    </>
  );
}
