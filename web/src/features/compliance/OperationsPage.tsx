import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Activity, AlertTriangle, Coins, Gauge } from 'lucide-react';
import { api } from '../../api/client';
import type { Metrics } from '../../api/types';
import { useAuth } from '../../auth/AuthProvider';
import {
  Badge,
  Card,
  EmptyState,
  ErrorNotice,
  LoadingRows,
  PageHeader,
  Segmented,
  Stat,
  humanError,
} from '../../components/ui';

const WORKFLOW: Record<string, string> = {
  triage: 'Triage & booking',
  records: 'Records answers',
  scribe: 'Consultation scribe',
  assistant: 'Care assistant',
  ingest: 'Report ingest',
};

const ms = (value: number | null | undefined) =>
  value == null
    ? '—'
    : value >= 1000
      ? `${(value / 1000).toFixed(1)} s`
      : `${Math.round(value)} ms`;
const pct = (value: number | null | undefined) =>
  value == null ? '—' : `${(value * 100).toFixed(1)}%`;
const usd = (value: number | string | null | undefined) =>
  value == null
    ? '—'
    : `$${Number(value).toFixed(Number(value) < 0.01 ? 4 : 2)}`;

/** Compliance home: how the assistant is performing and what it costs, from in-boundary traces. */
export function OperationsPage() {
  const { auth } = useAuth();
  const [hours, setHours] = useState<'1' | '24' | '168'>('24');
  const { data, isPending, error } = useQuery({
    queryKey: ['metrics', hours, auth.user_id],
    queryFn: () => api<Metrics>(`/api/ops/metrics?hours=${hours}`, {}, auth),
    refetchInterval: 30_000,
  });
  const runs = data?.runs ?? [];
  const totalRuns = runs.reduce((sum, run) => sum + run.runs, 0);
  const errorRate = totalRuns
    ? runs.reduce((sum, run) => sum + (run.error_rate ?? 0) * run.runs, 0) /
      totalRuns
    : null;
  const models = data?.models ?? [];
  const spend = models.reduce((sum, model) => sum + Number(model.cost ?? 0), 0);
  const unpriced = models.some((model) => model.unpriced_calls > 0);
  const worstP95 = runs.reduce(
    (worst, run) => Math.max(worst, run.p95_ms ?? 0),
    0,
  );

  return (
    <>
      <PageHeader
        eyebrow="Governance"
        title="Operations"
        description="Latency, reliability and model spend for every workflow. Traces hold timings and token counts only, never patient text."
        action={
          <Segmented
            label="Time window"
            value={hours}
            onChange={setHours}
            options={[
              { value: '1', label: '1 h' },
              { value: '24', label: '24 h' },
              { value: '168', label: '7 days' },
            ]}
          />
        }
      />
      {error ? (
        <ErrorNotice message={humanError(error)} />
      ) : (
        <>
          <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat
              label="Runs"
              value={isPending ? '—' : totalRuns.toLocaleString('en-IN')}
              icon={<Activity size={15} />}
            />
            <Stat
              label="Error rate"
              value={isPending ? '—' : pct(errorRate)}
              tone={errorRate && errorRate > 0.01 ? 'red' : 'green'}
              icon={<AlertTriangle size={15} />}
              hint="Budget: 1%"
            />
            <Stat
              label="Slowest workflow p95"
              value={isPending ? '—' : ms(worstP95)}
              icon={<Gauge size={15} />}
            />
            <Stat
              label="Model spend"
              value={isPending ? '—' : usd(spend)}
              icon={<Coins size={15} />}
              hint={
                unpriced
                  ? 'Some calls are unpriced'
                  : `Prices as of ${models[0]?.price_list_date ?? '—'}`
              }
              tone={unpriced ? 'amber' : 'neutral'}
            />
          </div>
          <div className="grid gap-5 xl:grid-cols-2">
            <Card title="Workflows" bodyClassName="">
              {isPending ? (
                <LoadingRows />
              ) : runs.length ? (
                <div className="overflow-x-auto">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Workflow</th>
                        <th className="text-right">Runs</th>
                        <th className="text-right">p50</th>
                        <th className="text-right">p95</th>
                        <th className="text-right">Errors</th>
                        <th className="text-right">Cost / run</th>
                      </tr>
                    </thead>
                    <tbody>
                      {runs.map((run) => (
                        <tr key={run.workflow}>
                          <td className="font-medium">
                            {WORKFLOW[run.workflow] ?? run.workflow}
                          </td>
                          <td className="text-right">
                            {run.runs.toLocaleString('en-IN')}
                          </td>
                          <td className="text-right">{ms(run.p50_ms)}</td>
                          <td className="text-right">{ms(run.p95_ms)}</td>
                          <td className="text-right">{pct(run.error_rate)}</td>
                          <td className="text-right">
                            {data?.cost_per_run?.[run.workflow] === null ? (
                              <Badge tone="amber">Unpriced</Badge>
                            ) : (
                              usd(data?.cost_per_run?.[run.workflow])
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <EmptyState
                  icon={<Activity size={18} />}
                  title="No runs in this window"
                  description="Runs appear as people use the assistant."
                />
              )}
            </Card>
            <Card title="Models" bodyClassName="">
              {isPending ? (
                <LoadingRows />
              ) : models.length ? (
                <div className="overflow-x-auto">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Model · workflow</th>
                        <th className="text-right">Calls</th>
                        <th className="text-right">Tokens in / out</th>
                        <th className="text-right">p95</th>
                        <th className="text-right">Cost</th>
                      </tr>
                    </thead>
                    <tbody>
                      {models.map((model) => (
                        <tr key={`${model.workflow}-${model.model}`}>
                          <td>
                            <span className="block font-medium">
                              {model.model.split(':').pop()}
                            </span>
                            <span className="text-[12px] text-muted">
                              {WORKFLOW[model.workflow] ?? model.workflow}
                            </span>
                          </td>
                          <td className="text-right">{model.calls}</td>
                          <td className="text-right">
                            {(model.tokens_in ?? 0).toLocaleString('en-IN')} /{' '}
                            {(model.tokens_out ?? 0).toLocaleString('en-IN')}
                            {model.tokens_estimated && (
                              <span
                                className="ml-1 text-[11px] text-amber-700"
                                title="Some token counts are estimated"
                              >
                                est.
                              </span>
                            )}
                          </td>
                          <td className="text-right">{ms(model.p95_ms)}</td>
                          <td className="text-right">
                            {model.unpriced_calls ? (
                              <Badge tone="amber">Unpriced</Badge>
                            ) : (
                              usd(model.cost)
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <EmptyState
                  icon={<Coins size={18} />}
                  title="No model calls"
                  description="Model calls appear once a provider is configured."
                />
              )}
            </Card>
            <Card
              title="Slowest steps"
              className="xl:col-span-2"
              bodyClassName=""
            >
              {isPending ? (
                <LoadingRows />
              ) : data?.slowest_nodes?.length ? (
                <div className="overflow-x-auto">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Step</th>
                        <th>Workflow</th>
                        <th className="text-right">Calls</th>
                        <th className="text-right">p95</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(data.slowest_nodes ?? []).slice(0, 8).map((node) => (
                        <tr key={`${node.workflow}-${node.name}`}>
                          <td className="font-mono text-[12px]">{node.name}</td>
                          <td className="text-muted">
                            {WORKFLOW[node.workflow] ?? node.workflow}
                          </td>
                          <td className="text-right">{node.calls}</td>
                          <td className="text-right">{ms(node.p95_ms)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <EmptyState
                  icon={<Gauge size={18} />}
                  title="No steps recorded"
                  description="Graph steps appear after the first runs."
                />
              )}
              {data && (
                <p className="border-t border-line px-5 py-3 text-[12px] text-muted">
                  {data.cost_formula}
                </p>
              )}
            </Card>
          </div>
        </>
      )}
    </>
  );
}
