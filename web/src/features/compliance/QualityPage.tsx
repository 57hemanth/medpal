import { useQuery } from '@tanstack/react-query';
import { Gauge } from 'lucide-react';
import { api } from '../../api/client';
import type { Quality } from '../../api/types';
import { useAuth } from '../../auth/AuthProvider';
import {
  Badge,
  Card,
  EmptyState,
  ErrorNotice,
  LoadingRows,
  PageHeader,
  Stat,
  humanError,
} from '../../components/ui';

const pct = (value: unknown) =>
  typeof value === 'number' ? `${Math.round(value * 100)}%` : '—';

const GATE_LABELS: Record<string, string> = {
  red_flag_recall: 'Emergency recall = 100%',
  over_triage: 'Over-triage ≤ 10%',
  specialty_accuracy: 'Specialty accuracy ≥ 85%',
  doctor_review_recall: 'Advice questions to a doctor = 100%',
  over_refusal: 'Plain record questions refused ≤ 10%',
};

const AREA_LABELS: Record<string, string> = {
  records: 'Records answers',
  'doctor-review (held-out)': 'Advice questions (held-out)',
  routing: 'Assistant routing',
  scribe: 'Note drafts',
  fallback: 'Provider fallback',
  metering: 'Cost metering',
  'red flags (held-out)': 'Emergencies (held-out)',
  'specialty (unseen)': 'Specialty (unseen)',
};

/** What the release gates and the latest real-model check measured, from the run files themselves. */
export function QualityPage() {
  const { auth } = useAuth();
  const { data, isPending, error } = useQuery({
    queryKey: ['quality', auth.user_id],
    queryFn: () => api<Quality>('/api/ops/quality', {}, auth),
  });
  const e = data?.evaluation;
  const live = data?.live;

  return (
    <>
      <PageHeader
        eyebrow="Governance"
        title="Quality"
        description="The release gates on every build, and the latest check against the real AI model. Numbers come straight from the run files; held-out sets are never tuned against."
      />
      {isPending ? (
        <Card>
          <LoadingRows rows={4} />
        </Card>
      ) : error ? (
        <ErrorNotice message={humanError(error)} />
      ) : (
        <div className="space-y-5">
          {e ? (
            <>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Stat
                  label="Emergency recall (gated set)"
                  value={pct(e.red_flag_recall)}
                  tone="green"
                />
                <Stat label="Over-triage" value={pct(e.over_triage)} />
                <Stat
                  label="Specialty accuracy (gated set)"
                  value={pct(e.specialty_accuracy)}
                  tone="green"
                />
                <Stat
                  label="Advice questions sent to a doctor"
                  value={pct(e.doctor_review_recall)}
                  tone="green"
                />
              </div>
              <Card
                title="Release gates"
                action={
                  <span className="text-[12px] text-muted">{e.file}</span>
                }
              >
                <ul className="grid gap-2 sm:grid-cols-2">
                  {Object.entries(e.gates ?? {}).map(([gate, passed]) => (
                    <li
                      key={gate}
                      className="flex items-center justify-between gap-3 rounded-lg border border-line px-3 py-2 text-[13px]"
                    >
                      {GATE_LABELS[gate] ?? gate}
                      <Badge tone={passed ? 'green' : 'red'}>
                        {passed ? 'Pass' : 'Fail'}
                      </Badge>
                    </li>
                  ))}
                </ul>
                <p className="mt-4 text-[13px] text-muted">
                  Rules alone on held-out phrasings (reported, never a gate):
                  emergencies {pct(e.holdout_recall_rules_only)}, specialty
                  right {pct(e.specialty_holdout_right)}, advice questions{' '}
                  {pct(e.doctor_review_holdout_recall)}. The safety questions
                  and the AI step cover what rules miss; see the live check
                  below.
                </p>
              </Card>
            </>
          ) : (
            <Card>
              <EmptyState
                icon={<Gauge size={18} />}
                title="No evaluation run yet"
                description="Run make eval to record one."
              />
            </Card>
          )}
          <Card
            title="Latest check against the real AI model"
            action={
              live && (
                <span className="text-[12px] text-muted">
                  {new Date(live.run_at).toLocaleString('en-IN')}
                </span>
              )
            }
            bodyClassName=""
          >
            {live ? (
              <>
                <div className="overflow-x-auto">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Area</th>
                        <th className="text-right">Passed</th>
                        <th className="text-right">Cases</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(live.areas).map(([area, counts]) => (
                        <tr key={area}>
                          <td>{AREA_LABELS[area] ?? area}</td>
                          <td className="text-right font-semibold">
                            {counts.passed}
                          </td>
                          <td className="text-right text-muted">
                            {counts.total}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <ul className="space-y-1 border-t border-line px-5 py-3 text-[13px] text-muted">
                  {live.summary.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </>
            ) : (
              <EmptyState
                icon={<Gauge size={18} />}
                title="No live check recorded yet"
                description="Run make live-check with a model key configured."
              />
            )}
          </Card>
        </div>
      )}
    </>
  );
}
