import { useDeferredValue, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Pencil, Pill, Plus } from 'lucide-react';
import { api } from '../../api/client';
import type { Medicine } from '../../api/types';
import { useAuth } from '../../auth/AuthProvider';
import {
  Badge,
  Button,
  Card,
  Modal,
  EmptyState,
  ErrorNotice,
  LoadingRows,
  PageHeader,
  humanError,
} from '../../components/ui';

const FIELDS = [
  ['name', 'Brand name', 'e.g. Dolo 650'],
  ['composition', 'Composition', 'e.g. Paracetamol (650mg)'],
  ['therapeutic_class', 'Class', 'e.g. Analgesic'],
  ['manufacturer', 'Manufacturer', 'e.g. Micro Labs'],
  ['pack_size', 'Pack', 'e.g. strip of 15 tablets'],
] as const;

/** Add a medicine to the catalogue, or correct one. Pharmacists only; every change is audited. */
function MedicineForm({
  medicine,
  onClose,
}: {
  medicine: Medicine | null;
  onClose: () => void;
}) {
  const { auth } = useAuth();
  const client = useQueryClient();
  const [values, setValues] = useState<Record<string, string>>(() => ({
    name: medicine?.name ?? '',
    composition: medicine?.composition ?? '',
    therapeutic_class: medicine?.therapeutic_class ?? '',
    manufacturer: medicine?.manufacturer ?? '',
    pack_size: medicine?.pack_size ?? '',
    price_inr: medicine?.price_inr != null ? String(medicine.price_inr) : '',
  }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function save() {
    if (!values.name.trim() || !values.composition.trim()) {
      setError('A medicine needs a name and a composition.');
      return;
    }
    const body: Record<string, string | number | null> = {};
    for (const [key] of FIELDS) body[key] = values[key].trim() || null;
    body.price_inr = values.price_inr.trim() ? Number(values.price_inr) : null;
    setBusy(true);
    setError('');
    try {
      await api(
        medicine
          ? `/api/pharmacy/medicines/${medicine.medicine_id}`
          : '/api/pharmacy/medicines',
        { method: medicine ? 'PATCH' : 'POST', body: JSON.stringify(body) },
        auth,
      );
      await client.invalidateQueries({ queryKey: ['medicines'] });
      onClose();
    } catch (cause) {
      setError(humanError(cause));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={medicine ? `Edit ${medicine.name}` : 'Add a medicine'}
      description={
        medicine
          ? 'Corrections apply across the network.'
          : 'Added to the catalogue for every clinic. Doctors can prescribe it once it is here.'
      }
      onClose={onClose}
      onSubmit={save}
      submitLabel={medicine ? 'Save changes' : 'Add medicine'}
      busy={busy}
      error={error}
    >
      {FIELDS.map(([key, label, placeholder]) => (
        <label key={key} className="block">
          <span className="field-label">{label}</span>
          <input
            className="field"
            maxLength={200}
            placeholder={placeholder}
            value={values[key]}
            onChange={(event) =>
              setValues((current) => ({
                ...current,
                [key]: event.target.value,
              }))
            }
          />
        </label>
      ))}
      <label className="block">
        <span className="field-label">Price (₹ per pack)</span>
        <input
          className="field"
          type="number"
          min={0}
          step="0.01"
          inputMode="decimal"
          value={values.price_inr}
          onChange={(event) =>
            setValues((current) => ({
              ...current,
              price_inr: event.target.value,
            }))
          }
        />
      </label>
    </Modal>
  );
}

/** The medicine catalogue for doctors and pharmacists: what exists, what it is, and where it's available. */
export function MedicinesPage() {
  const { auth } = useAuth();
  const [query, setQuery] = useState('');
  const [editing, setEditing] = useState<Medicine | 'new' | null>(null);
  const canEdit = auth.role === 'pharmacist';
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
        action={
          canEdit && (
            <Button onClick={() => setEditing('new')}>
              <Plus size={15} />
              Add medicine
            </Button>
          )
        }
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
                  {canEdit && (
                    <th>
                      <span className="sr-only">Actions</span>
                    </th>
                  )}
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
                      {canEdit && (
                        <td className="text-right">
                          <button
                            type="button"
                            className="btn btn-ghost px-2.5 text-xs"
                            aria-label={`Edit ${m.name}`}
                            onClick={() => setEditing(m)}
                          >
                            <Pencil size={13} />
                            Edit
                          </button>
                        </td>
                      )}
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
      {editing && (
        <MedicineForm
          medicine={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
        />
      )}
    </>
  );
}
