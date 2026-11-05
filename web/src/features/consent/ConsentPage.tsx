import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Clock3, LockKeyhole, ShieldCheck, Users } from 'lucide-react';
import { api } from '../../api/client';
import type { Consent } from '../../api/types';
import { useAuth } from '../../auth/AuthProvider';
import {
  Badge,
  Button,
  EmptyState,
  ErrorNotice,
  PageHeader,
  PrivacyNote,
  formatDate,
  humanError,
} from '../../components/ui';

export function ConsentPage() {
  const { auth } = useAuth();
  const [error, setError] = useState('');
  const [confirm, setConfirm] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const {
    data = [],
    refetch,
    isPending,
    error: queryError,
  } = useQuery({
    queryKey: ['consents', auth.user_id, auth.role],
    queryFn: () => api<Consent[]>('/api/consents', {}, auth),
    retry: false,
  });
  // A patient can revoke what they shared from their OWN record; consents someone else granted them
  // (e.g. a parent sharing with Asha) are shown read-only, and only the granting patient can revoke them.
  const mine = (consent: Consent) =>
    auth.role === 'patient' &&
    consent.patient_id === auth.acting_for_patient_id;
  const ordered = [...data].sort((a, b) => Number(mine(b)) - Number(mine(a)));
  async function revoke(id: string) {
    setPending(id);
    setError('');
    try {
      await api(`/api/consents/${id}/revoke`, { method: 'POST' }, auth);
      setConfirm(null);
      await refetch();
    } catch (cause) {
      setError(humanError(cause));
    } finally {
      setPending(null);
    }
  }
  return (
    <section>
      <PageHeader
        eyebrow="Privacy"
        title="Sharing & consent"
        description="Who can see which records, for what purpose, and until when. Revoking takes effect immediately."
      />
      <div className="mb-6">
        <ErrorNotice
          message={error || (queryError ? humanError(queryError) : '')}
        />
      </div>
      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_290px]">
        <div className="panel overflow-hidden">
          <div className="flex items-center justify-between border-b border-line px-6 py-5">
            <h2 className="text-sm font-semibold">
              {auth.role === 'caregiver'
                ? 'Access shared with you'
                : 'Sharing permissions'}
            </h2>
            <Badge>
              {data.length} {data.length === 1 ? 'permission' : 'permissions'}
            </Badge>
          </div>
          {isPending ? (
            <p role="status" className="p-6 text-sm text-muted">
              Loading permissions…
            </p>
          ) : data.length === 0 ? (
            <EmptyState
              icon={<Users size={24} />}
              title="Your care circle starts with you."
              description="There are no sharing permissions for this identity. When access is granted, its scope and expiry appear here."
            />
          ) : (
            <div className="divide-y divide-line">
              {ordered.map((consent) => {
                const expired = new Date(consent.expires_at) <= new Date();
                const inactive = consent.revoked_at || expired;
                return (
                  <article key={consent.consent_id} className="p-5 sm:p-6">
                    <div className="flex items-start gap-3">
                      <span className="flex size-11 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-700">
                        <Users size={20} />
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div>
                            <h3 className="text-sm font-semibold">
                              {mine(consent)
                                ? (consent.grantee_name ?? 'Care circle member')
                                : (consent.patient_name ?? 'Another patient')}
                            </h3>
                            <p className="mt-0.5 text-[12px] text-muted">
                              {mine(consent)
                                ? 'Can see your records'
                                : 'Shared their records with you'}
                            </p>
                          </div>
                          <Badge tone={inactive ? 'neutral' : 'green'}>
                            {consent.revoked_at
                              ? 'Revoked'
                              : expired
                                ? 'Expired'
                                : 'Active access'}
                          </Badge>
                        </div>
                        <p className="mt-1.5 text-xs capitalize text-muted">
                          {consent.purpose}
                        </p>
                        <div className="mt-4 flex flex-wrap gap-2">
                          {consent.scope.map((scope) => (
                            <span
                              key={scope}
                              className="rounded-lg border border-line bg-canvas px-2.5 py-1.5 text-[11px] font-medium text-slate-600"
                            >
                              {scope === 'records:read'
                                ? 'View health records'
                                : scope.replaceAll(':', ' · ')}
                            </span>
                          ))}
                        </div>
                        <p className="mt-4 flex items-center gap-1.5 text-xs text-muted">
                          <Clock3 size={13} />
                          {consent.revoked_at
                            ? `Revoked ${formatDate(consent.revoked_at)}`
                            : `Access ends ${formatDate(consent.expires_at)}`}
                        </p>
                        <details className="mt-2 text-[11px] text-muted">
                          <summary className="cursor-pointer py-2">
                            Permission details
                          </summary>
                          <p className="break-all leading-relaxed">
                            Member reference: {consent.grantee_user_id}
                          </p>
                        </details>
                        {mine(consent) && !inactive && (
                          <div className="mt-3">
                            {confirm === consent.consent_id ? (
                              <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
                                <p className="text-xs leading-relaxed text-amber-900">
                                  Revoke this person’s access? They will no
                                  longer be able to read the shared records.
                                </p>
                                <div className="mt-3 flex gap-2">
                                  <Button
                                    variant="secondary"
                                    onClick={() => setConfirm(null)}
                                    disabled={!!pending}
                                  >
                                    Keep access
                                  </Button>
                                  <Button
                                    onClick={() =>
                                      void revoke(consent.consent_id)
                                    }
                                    busy={pending === consent.consent_id}
                                  >
                                    Revoke access
                                  </Button>
                                </div>
                              </div>
                            ) : (
                              <Button
                                variant="secondary"
                                onClick={() => setConfirm(consent.consent_id)}
                              >
                                <LockKeyhole size={14} />
                                Revoke access
                              </Button>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </div>
        <aside className="space-y-5">
          <div className="rounded-2xl border border-brand-100 bg-brand-50 p-6">
            <ShieldCheck size={25} className="text-brand-700" />
            <h2 className="mt-4 text-sm font-semibold">You’re in control.</h2>
            <p className="mt-2 text-xs leading-6 text-brand-800">
              Every permission has a purpose, a scope, and an expiry. You can
              revoke access at any time.
            </p>
          </div>
          <div className="panel p-5">
            <p className="eyebrow mb-4">Sharing, thoughtfully</p>
            <div className="space-y-5">
              {[
                [
                  'Specific',
                  'Only the records and actions covered by a permission are shared.',
                ],
                [
                  'Time-bound',
                  'Access ends automatically when the permission expires.',
                ],
                [
                  'Revocable',
                  'Your choice is checked each time someone accesses a record.',
                ],
              ].map(([title, description]) => (
                <div key={title}>
                  <h3 className="text-xs font-semibold">{title}</h3>
                  <p className="mt-1.5 text-xs leading-relaxed text-muted">
                    {description}
                  </p>
                </div>
              ))}
            </div>
          </div>
          <PrivacyNote>
            Your health information stays within the access you allow.
          </PrivacyNote>
        </aside>
      </div>
    </section>
  );
}
