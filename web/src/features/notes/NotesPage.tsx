import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { NotebookPen, PenLine, Repeat2 } from 'lucide-react';
import { api } from '../../api/client';
import type { SignedNote } from '../../api/types';
import { useAuth } from '../../auth/AuthProvider';
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNotice,
  LoadingRows,
  Modal,
  PageHeader,
  Segmented,
  StatusPill,
  formatDateTime,
  humanError,
} from '../../components/ui';

type Section = 'subjective' | 'objective' | 'assessment' | 'plan';
type Rx = SignedNote['prescriptions'][number];

const SECTIONS: [Section, string][] = [
  ['subjective', 'Subjective'],
  ['objective', 'Objective'],
  ['assessment', 'Assessment'],
  ['plan', 'Plan'],
];

/** A new version of a signed note. The signed version is kept and stays visible. */
function AmendNote({
  note,
  onClose,
}: {
  note: SignedNote;
  onClose: () => void;
}) {
  const { auth } = useAuth();
  const client = useQueryClient();
  const [soap, setSoap] = useState<Record<Section, string>>(() => ({
    subjective: note.soap_json.subjective ?? '',
    objective: note.soap_json.objective ?? '',
    assessment: note.soap_json.assessment ?? '',
    plan: note.soap_json.plan ?? '',
  }));
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function save() {
    if (reason.trim().length < 3) {
      setError('Say why the note is being amended.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      await api(
        `/api/scribe/notes/${note.note_id}/amend`,
        { method: 'POST', body: JSON.stringify({ ...soap, reason }) },
        auth,
      );
      await client.invalidateQueries({ queryKey: ['notes'] });
      onClose();
    } catch (cause) {
      setError(humanError(cause));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title="Amend signed note"
      description={`Saved as version ${note.version + 1}. Version ${note.version} is kept unchanged and stays visible to the patient and to audit.`}
      onClose={onClose}
      onSubmit={save}
      submitLabel={`Sign version ${note.version + 1}`}
      busy={busy}
      error={error}
    >
      {SECTIONS.map(([key, label]) => (
        <label key={key} className="block">
          <span className="field-label">{label}</span>
          <textarea
            className="field min-h-20"
            value={soap[key]}
            onChange={(event) =>
              setSoap((current) => ({ ...current, [key]: event.target.value }))
            }
          />
        </label>
      ))}
      <label className="block">
        <span className="field-label">Reason for the amendment</span>
        <input
          className="field"
          maxLength={300}
          placeholder="e.g. Follow-up interval was missing from the plan"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </label>
    </Modal>
  );
}

/** Stop a prescription, or stop it and prescribe another medicine instead. Never an edit in place. */
function ChangePrescription({ rx, onClose }: { rx: Rx; onClose: () => void }) {
  const { auth } = useAuth();
  const client = useQueryClient();
  const [mode, setMode] = useState<'stop' | 'replace'>('stop');
  const [replacement, setReplacement] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function save() {
    if (mode === 'replace' && !replacement.trim()) {
      setError('Name the medicine to prescribe instead.');
      return;
    }
    if (reason.trim().length < 3) {
      setError('Add a reason; the patient is told their prescription changed.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      await api(
        `/api/scribe/prescriptions/${rx.rx_id}/change`,
        {
          method: 'POST',
          body: JSON.stringify({
            reason,
            replacement: mode === 'replace' ? replacement : null,
          }),
        },
        auth,
      );
      await client.invalidateQueries({ queryKey: ['notes'] });
      onClose();
    } catch (cause) {
      setError(humanError(cause));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={`Change ${rx.medicine}`}
      description="The prescription is stopped, not edited: its pharmacy hold is released and the patient is told."
      onClose={onClose}
      onSubmit={save}
      submitLabel={mode === 'stop' ? 'Stop prescription' : 'Replace'}
      busy={busy}
      error={error}
      danger={mode === 'stop'}
    >
      <Segmented
        label="Change"
        value={mode}
        onChange={setMode}
        options={[
          { value: 'stop', label: 'Stop it' },
          { value: 'replace', label: 'Replace with another' },
        ]}
      />
      {mode === 'replace' && (
        <label className="block">
          <span className="field-label">Prescribe instead</span>
          <input
            className="field"
            maxLength={200}
            placeholder="e.g. Cetirizine"
            value={replacement}
            onChange={(event) => setReplacement(event.target.value)}
          />
          <span className="mt-1 block text-[12px] text-muted">
            Held at the same clinic's pharmacy if it's in stock.
          </span>
        </label>
      )}
      <label className="block">
        <span className="field-label">Reason</span>
        <input
          className="field"
          maxLength={300}
          placeholder="e.g. Rash after the first dose"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </label>
    </Modal>
  );
}

/** Signed consultation notes: a doctor's patients, or a patient's own visits. Every read is audited. */
export function NotesPage() {
  const { auth } = useAuth();
  const doctor = auth.role === 'doctor';
  const [amending, setAmending] = useState<SignedNote | null>(null);
  const [changing, setChanging] = useState<Rx | null>(null);
  const {
    data = [],
    isPending,
    error,
  } = useQuery({
    queryKey: ['notes', auth.user_id, auth.role],
    queryFn: () => api<SignedNote[]>('/api/scribe/notes', {}, auth),
  });

  return (
    <>
      <PageHeader
        eyebrow={doctor ? 'Clinical' : 'Care'}
        title={doctor ? 'Signed notes' : 'Visit notes'}
        description={
          doctor
            ? 'Notes you and colleagues signed for your patients, with the transcript each was drafted from and where its medicines are held. Amend your own notes or change their prescriptions here.'
            : 'What your doctor recorded at each visit, and where your medicines are held. Signed notes are never edited: a correction is added as a new version and the earlier one stays visible.'
        }
      />
      {isPending ? (
        <Card>
          <LoadingRows rows={4} />
        </Card>
      ) : error ? (
        <ErrorNotice message={humanError(error)} />
      ) : data.length ? (
        <div className="space-y-4">
          {data.map((note) => {
            const amendments = note.edit_history.filter(
              (entry) => entry.action === 'amended',
            );
            const canChange = doctor && note.mine;
            return (
              <Card
                key={note.note_id}
                title={
                  <span>
                    {doctor
                      ? (note.patient_name ?? 'Patient')
                      : (note.doctor_name ?? 'Doctor')}
                    <span className="ml-2 font-normal text-muted">
                      {formatDateTime(note.signed_at)}
                      {note.clinic_name ? ` · ${note.clinic_name}` : ''}
                    </span>
                  </span>
                }
                action={
                  <span className="flex items-center gap-2">
                    <Badge tone={amendments.length ? 'blue' : 'green'}>
                      {amendments.length ? 'Amended' : 'Signed'} · v
                      {note.version}
                    </Badge>
                    {canChange && (
                      <Button
                        variant="ghost"
                        className="px-2.5 text-xs"
                        onClick={() => setAmending(note)}
                      >
                        <PenLine size={13} />
                        Amend
                      </Button>
                    )}
                  </span>
                }
              >
                <div className="grid gap-4 md:grid-cols-2">
                  {SECTIONS.map(([key, label]) => (
                    <div key={key}>
                      <p className="eyebrow mb-1">{label}</p>
                      <p className="whitespace-pre-wrap text-[14px] leading-relaxed">
                        {note.soap_json[key] || '—'}
                      </p>
                    </div>
                  ))}
                </div>
                {note.prescriptions.length > 0 && (
                  <div className="mt-4 border-t border-line pt-4">
                    <p className="eyebrow mb-2">Medicines</p>
                    <ul className="space-y-2">
                      {note.prescriptions.map((rx) => (
                        <li
                          key={rx.rx_id}
                          className="flex flex-wrap items-center gap-2 rounded-lg border border-line px-3 py-2 text-[13px]"
                        >
                          <span
                            className={`font-medium ${rx.rx_status === 'stopped' ? 'text-muted line-through' : ''}`}
                          >
                            {rx.medicine}
                          </span>
                          <StatusPill
                            status={
                              rx.rx_status === 'stopped'
                                ? 'stopped'
                                : (rx.status ?? 'not_held')
                            }
                          />
                          {rx.clinic && rx.rx_status === 'active' && (
                            <span className="text-[12px] text-muted">
                              {rx.clinic}
                            </span>
                          )}
                          {rx.replaces && (
                            <span className="text-[12px] text-muted">
                              replaces {rx.replaces}
                            </span>
                          )}
                          {rx.stop_reason && (
                            <span className="text-[12px] text-muted">
                              · {rx.stop_reason}
                            </span>
                          )}
                          {canChange && rx.rx_status === 'active' && (
                            <button
                              type="button"
                              className="btn btn-ghost ml-auto px-2 text-xs"
                              aria-label={`Change ${rx.medicine}`}
                              onClick={() => setChanging(rx)}
                            >
                              <Repeat2 size={13} />
                              Change
                            </button>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {note.earlier_versions.length > 0 && (
                  <details className="mt-4 border-t border-line pt-3 text-[13px]">
                    <summary className="cursor-pointer font-medium text-brand-700">
                      Earlier versions ({note.earlier_versions.length})
                    </summary>
                    <ul className="mt-2 space-y-3">
                      {amendments
                        .slice()
                        .reverse()
                        .map((entry) => (
                          <li key={`reason-${entry.version}`}>
                            <span className="font-medium">
                              Version {entry.version}
                            </span>
                            <span className="text-muted">
                              {' '}
                              · changed {(entry.fields ?? []).join(', ')} ·{' '}
                              {entry.reason}
                              {entry.at ? ` · ${formatDateTime(entry.at)}` : ''}
                            </span>
                          </li>
                        ))}
                      {note.earlier_versions.map((earlier) => (
                        <li
                          key={earlier.version}
                          className="rounded-lg bg-canvas p-3"
                        >
                          <p className="mb-2 font-medium">
                            Version {earlier.version} · signed{' '}
                            {formatDateTime(earlier.signed_at)}
                          </p>
                          {SECTIONS.map(([key, label]) => (
                            <p
                              key={key}
                              className="whitespace-pre-wrap text-muted"
                            >
                              <span className="font-medium text-ink">
                                {label}:
                              </span>{' '}
                              {earlier.soap_json[key] || '—'}
                            </p>
                          ))}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
                <details className="mt-4 border-t border-line pt-3 text-[13px]">
                  <summary className="cursor-pointer font-medium text-brand-700">
                    Consultation transcript
                  </summary>
                  <p className="mt-2 whitespace-pre-wrap rounded-lg bg-canvas p-3 leading-relaxed text-muted">
                    {note.transcript ?? 'No transcript was kept for this note.'}
                  </p>
                  <p className="mt-2 font-mono text-[11px] text-subtle">
                    Content hash {note.content_hash.slice(0, 16)}…
                  </p>
                </details>
              </Card>
            );
          })}
        </div>
      ) : (
        <Card>
          <EmptyState
            icon={<NotebookPen size={18} />}
            title="No signed notes yet"
            description={
              doctor
                ? 'Notes appear here as soon as you sign them in Consultations.'
                : 'Notes from your visits appear here once your doctor signs them.'
            }
          />
        </Card>
      )}
      {amending && (
        <AmendNote note={amending} onClose={() => setAmending(null)} />
      )}
      {changing && (
        <ChangePrescription rx={changing} onClose={() => setChanging(null)} />
      )}
    </>
  );
}
