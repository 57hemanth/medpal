import { useDeferredValue, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Pill } from 'lucide-react';
import { api } from '../../api/client';
import type { Medicine } from '../../api/types';
import { useAuth } from '../../auth/AuthProvider';
import {
  Badge,
  Card,
  EmptyState,
  ErrorNotice,
  LoadingRows,
  PageHeader,
  humanError,
} from '../../components/ui';

/** The medicine catalogue for doctors and pharmacists: what exists, what it is, and where it's available. */
export function MedicinesPage() {
  const { auth } = useAuth();
  const [query, setQuery] = useState('');
  const deferred = useDeferredValue(query.trim());
  const {
    data = [],
    isPending,
    error,
  } = useQuery({
    queryKey: ['medicines', deferred, auth.user_id],
    queryFn: () =>
      api<Medicine[]>(
        `/api/pharmacy/medicines?q=${encodeURIComponent(deferred)}`,
        {},
        auth,
      ),
  });

  return (
    <>
      <PageHeader
        eyebrow={auth.role === 'pharmacist' ? 'Pharmacy' : 'Clinical'}
        title="Medicines"
        description="The formulary across the network: composition, class, pack and price, and how many clinics have it available now."
      />
      <Card bodyClassName="">
        <div className="border-b border-line px-4 py-3">
          <label className="block sm:w-96">
            <span className="sr-only">Search medicines</span>
            <input
              className="field py-2"
              placeholder="Search by name, ingredient or class (e.g. statin)…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
        </div>
        {isPending ? (
          <LoadingRows rows={6} />
        ) : error ? (
          <div className="p-5">
            <ErrorNotice message={humanError(error)} />
          </div>
        ) : data.length ? (
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>Medicine</th>
                  <th>Class</th>
                  <th className="hidden md:table-cell">Pack</th>
                  <th className="hidden md:table-cell text-right">Price</th>
                  <th>Availability</th>
                </tr>
              </thead>
              <tbody>
                {data.map((m) => {
                  const share = m.clinics_total
                    ? m.clinics_available / m.clinics_total
                    : 0;
                  return (
                    <tr key={m.medicine_id}>
                      <td>
                        <span className="block font-medium">{m.name}</span>
                        <span className="text-[12px] text-muted">
                          {m.composition}
                          {m.manufacturer ? ` · ${m.manufacturer}` : ''}
                        </span>
                      </td>
                      <td className="text-muted">
                        {m.therapeutic_class ?? '—'}
                      </td>
                      <td className="hidden text-muted md:table-cell">
                        {m.pack_size ?? '—'}
                      </td>
                      <td className="hidden text-right md:table-cell">
                        {m.price_inr != null
                          ? `₹${Number(m.price_inr).toFixed(2)}`
                          : '—'}
                      </td>
                      <td>
                        <Badge
                          tone={
                            share >= 0.8 ? 'green' : share > 0 ? 'amber' : 'red'
                          }
                        >
                          {m.clinics_available} of {m.clinics_total} clinics
                        </Badge>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            icon={<Pill size={18} />}
            title="No medicines match"
            description="Try an ingredient (paracetamol) or a class (statin)."
          />
        )}
      </Card>
    </>
  );
}
