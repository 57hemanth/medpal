import { useQuery } from '@tanstack/react-query';
import { Pill } from 'lucide-react';
import { api } from '../../api/client';
import type { Prescription } from '../../api/types';
import { useAuth } from '../../auth/AuthProvider';
import {
  Card,
  EmptyState,
  ErrorNotice,
  LoadingRows,
  PageHeader,
  StatusPill,
  formatDate,
  humanError,
} from '../../components/ui';

function whereToCollect(rx: Prescription) {
  if (rx.rx_status === 'stopped')
    return `Stopped by your doctor${rx.stop_reason ? `: ${rx.stop_reason}` : ''}. Don't continue it unless your doctor tells you to.`;
  if (rx.reservation_status === 'reserved')
    return `Held for you at the ${rx.clinic_name} pharmacy`;
  if (rx.reservation_status === 'dispensed')
    return `Collected at ${rx.clinic_name}`;
  if (rx.reservation_status === 'released')
    return 'No longer held; ask the pharmacy';
  return 'Not in stock when prescribed; the pharmacy will advise';
}

/** A patient's prescriptions and where to collect them. */
export function PrescriptionsPage() {
  const { auth } = useAuth();
  const {
    data = [],
    isPending,
    error,
  } = useQuery({
    queryKey: ['prescriptions', auth.user_id, auth.role],
    queryFn: () => api<Prescription[]>('/api/prescriptions', {}, auth),
  });

  return (
    <>
      <PageHeader
        eyebrow="Care"
        title="Prescriptions"
        description="Medicines from your signed visit notes. When your doctor signs, anything in stock is held for you at that clinic's pharmacy."
      />
      <Card bodyClassName="">
        {isPending ? (
          <LoadingRows rows={4} />
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
                  {auth.role === 'caregiver' && <th>For</th>}
                  <th className="hidden md:table-cell">Prescribed by</th>
                  <th>Date</th>
                  <th>Collection</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {data.map((rx) => (
                  <tr key={rx.rx_id}>
                    <td>
                      <span
                        className={`block font-medium ${rx.rx_status === 'stopped' ? 'text-muted line-through' : ''}`}
                      >
                        {rx.medicine ?? rx.medicine_text}
                      </span>
                      {rx.replaces && (
                        <span className="block text-[12px] text-muted">
                          Replaces {rx.replaces}
                        </span>
                      )}
                      <span className="text-[12px] text-muted">
                        {[rx.composition, rx.pack_size]
                          .filter(Boolean)
                          .join(' · ')}
                      </span>
                    </td>
                    {auth.role === 'caregiver' && <td>{rx.patient_name}</td>}
                    <td className="hidden text-muted md:table-cell">
                      {rx.doctor_name ?? '—'}
                    </td>
                    <td className="whitespace-nowrap">
                      {formatDate(rx.signed_at)}
                    </td>
                    <td className="text-muted">{whereToCollect(rx)}</td>
                    <td>
                      <StatusPill
                        status={
                          rx.rx_status === 'stopped'
                            ? 'stopped'
                            : (rx.reservation_status ?? 'not_held')
                        }
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            icon={<Pill size={18} />}
            title="No prescriptions yet"
            description="Medicines your doctor prescribes appear here when they sign your visit note."
          />
        )}
      </Card>
    </>
  );
}
