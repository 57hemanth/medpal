import { useQuery } from '@tanstack/react-query';
import { NotebookPen } from 'lucide-react';
import { api } from '../../api/client';
import type { SignedNote } from '../../api/types';
import { useAuth } from '../../auth/AuthProvider';
import {
  Badge,
  Card,
  EmptyState,
  ErrorNotice,
  LoadingRows,
  PageHeader,
  StatusPill,
  formatDateTime,
  humanError,
} from '../../components/ui';

const SECTIONS: [keyof SignedNote['soap_json'], string][] = [
  ['subjective', 'Subjective'],
  ['objective', 'Objective'],
  ['assessment', 'Assessment'],
  ['plan', 'Plan'],
];

/** Signed consultation notes: a doctor's patients, or a patient's own visits. Every read is audited. */
export function NotesPage() {
  const { auth } = useAuth();
  const doctor = auth.role === 'doctor';
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
            ? 'Notes you and colleagues signed for your patients, with the transcript each was drafted from and where its medicines are held.'
            : 'What your doctor recorded at each visit, and where your medicines are held. Signed notes can never be changed.'
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
          {data.map((note) => (
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
              action={<Badge tone="green">Signed · v{note.version}</Badge>}
            >
              <div className="grid gap-4 md:grid-cols-2">
                {SECTIONS.map(([key, label]) => (
                  <div key={key}>
                    <p className="eyebrow mb-1">{label}</p>
                    <p className="whitespace-pre-wrap text-[14px] leading-relaxed">
                      {(note.soap_json[key] as string) || '—'}
                    </p>
                  </div>
                ))}
              </div>
              {note.prescriptions.length > 0 && (
                <div className="mt-4 border-t border-line pt-4">
                  <p className="eyebrow mb-2">Medicines</p>
                  <ul className="flex flex-wrap gap-2">
                    {note.prescriptions.map((rx) => (
                      <li
                        key={rx.medicine}
                        className="flex items-center gap-2 rounded-lg border border-line px-3 py-1.5 text-[13px]"
                      >
                        <span className="font-medium">{rx.medicine}</span>
                        <StatusPill status={rx.status ?? 'not_held'} />
                        {rx.clinic && (
                          <span className="text-[12px] text-muted">
                            {rx.clinic}
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <details className="mt-4 border-t border-line pt-3 text-[13px]">
                <summary className="cursor-pointer font-medium text-brand-700">
                  Consultation transcript
                  {doctor && note.edit_history.length > 0 && (
                    <span className="ml-2 font-normal text-muted">
                      · {note.edit_history.length} recorded{' '}
                      {note.edit_history.length === 1 ? 'change' : 'changes'}{' '}
                      before signing
                    </span>
                  )}
                </summary>
                <p className="mt-2 whitespace-pre-wrap rounded-lg bg-canvas p-3 leading-relaxed text-muted">
                  {note.transcript ?? 'No transcript was kept for this note.'}
                </p>
                <p className="mt-2 font-mono text-[11px] text-subtle">
                  Content hash {note.content_hash.slice(0, 16)}…
                </p>
              </details>
            </Card>
          ))}
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
    </>
  );
}
