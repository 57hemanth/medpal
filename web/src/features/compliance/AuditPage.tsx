import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ScrollText } from 'lucide-react';
import { api } from '../../api/client';
import type { AuditEvent } from '../../api/types';
import { useAuth } from '../../auth/AuthProvider';
import {
  Badge,
  Card,
  EmptyState,
  ErrorNotice,
  LoadingRows,
  PageHeader,
  formatDateTime,
  humanError,
} from '../../components/ui';

const RESOURCES = [
  { value: '', label: 'All records' },
  { value: 'document', label: 'Documents' },
  { value: 'appointment', label: 'Appointments' },
  { value: 'note_version', label: 'Signed notes' },
  { value: 'consent', label: 'Consent' },
  { value: 'encounter', label: 'Consultations' },
  { value: 'handoff_ticket', label: 'Handoffs' },
  { value: 'assistant.triage', label: 'Assistant → triage' },
  { value: 'assistant.records', label: 'Assistant → records' },
  { value: 'assistant.scribe', label: 'Assistant → scribe' },
];
const ACTIONS = [
  '',
  'read',
  'write',
  'upload',
  'cancel',
  'sign',
  'grant',
  'revoke',
  'update',
  'delegate',
];

/** Append-only audit trail: who touched which record, why, and under which trace. */
export function AuditPage() {
  const { auth } = useAuth();
  const [resource, setResource] = useState('');
  const [action, setAction] = useState('');
  const [shown, setShown] = useState(50);
  const params = new URLSearchParams({ limit: '200' });
  if (resource) params.set('resource', resource);
  if (action) params.set('action', action);
  const {
    data = [],
    isPending,
    error,
  } = useQuery({
    queryKey: ['audit', resource, action, auth.user_id],
    queryFn: () => api<AuditEvent[]>(`/api/audit?${params}`, {}, auth),
  });

  return (
    <>
      <PageHeader
        eyebrow="Governance"
        title="Audit log"
        description="Every write that touches patient data, and every record read, logged in the same transaction. Entries can't be edited or deleted, not even by a database administrator."
      />
      <Card bodyClassName="">
        <div className="flex flex-wrap gap-3 border-b border-line px-4 py-3">
          <label className="min-w-48">
            <span className="field-label">Record type</span>
            <select
              className="field py-2"
              value={resource}
              onChange={(event) => {
                setResource(event.target.value);
                setShown(50);
              }}
            >
              {RESOURCES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="min-w-40">
            <span className="field-label">Action</span>
            <select
              className="field py-2"
              value={action}
              onChange={(event) => {
                setAction(event.target.value);
                setShown(50);
              }}
            >
              {ACTIONS.map((value) => (
                <option key={value} value={value}>
                  {value
                    ? value[0].toUpperCase() + value.slice(1)
                    : 'All actions'}
                </option>
              ))}
            </select>
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
                  <th>When</th>
                  <th>Actor</th>
                  <th>Action</th>
                  <th>Record</th>
                  <th>Patient</th>
                  <th className="hidden lg:table-cell">Purpose</th>
                  <th className="hidden xl:table-cell">Trace</th>
                </tr>
              </thead>
              <tbody>
                {data.slice(0, shown).map((event) => (
                  <tr key={`${event.event_id}-${event.at}`}>
                    <td className="whitespace-nowrap">
                      {formatDateTime(event.at)}
                    </td>
                    <td>
                      <Badge>{event.actor_role}</Badge>
                    </td>
                    <td className="font-medium capitalize">{event.action}</td>
                    <td>
                      <span className="block">
                        {event.resource.replaceAll('_', ' ')}
                      </span>
                      <span className="font-mono text-[11px] text-muted">
                        {event.record_id.slice(0, 8)}
                      </span>
                    </td>
                    <td>{event.patient_name ?? '—'}</td>
                    <td className="hidden text-muted lg:table-cell">
                      {event.purpose}
                    </td>
                    <td className="hidden font-mono text-[11px] text-muted xl:table-cell">
                      {event.trace_id ? event.trace_id.slice(0, 8) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="flex items-center justify-between gap-3 border-t border-line px-4 py-3 text-[12px] text-muted">
              <span>
                Showing {Math.min(shown, data.length)} of {data.length} most
                recent events
              </span>
              {shown < data.length && (
                <button
                  className="btn btn-secondary"
                  onClick={() => setShown((value) => value + 50)}
                >
                  Show more
                </button>
              )}
            </div>
          </div>
        ) : (
          <EmptyState
            icon={<ScrollText size={18} />}
            title="No matching events"
            description="Try a different record type or action."
          />
        )}
      </Card>
    </>
  );
}
