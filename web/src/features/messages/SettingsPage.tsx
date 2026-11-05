import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, Mail, MailWarning } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../../api/client';
import type { ContactSettings, OutboxMessage } from '../../api/types';
import { useAuth } from '../../auth/AuthProvider';
import {
  Badge,
  Button,
  Card,
  ErrorNotice,
  LoadingRows,
  PageHeader,
  PrivacyNote,
  humanError,
} from '../../components/ui';
import { MessagesTable } from './MessagesTable';

/** A patient's email address and appointment-email choice, plus the emails sent to them. */
export function SettingsPage() {
  const { auth, me } = useAuth();
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const contactKey = ['contact', auth.user_id];
  const contact = useQuery({
    queryKey: contactKey,
    queryFn: () => api<ContactSettings>('/api/me/contact', {}, auth),
  });
  const messages = useQuery({
    queryKey: ['messages', auth.user_id, auth.role],
    queryFn: () => api<OutboxMessage[]>('/api/messages', {}, auth),
  });
  const [email, setEmail] = useState('');
  const [enabled, setEnabled] = useState(true);
  const [busy, setBusy] = useState<'save' | 'resend' | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    if (!contact.data) return;
    setEmail(contact.data.email ?? '');
    setEnabled(contact.data.email_notifications);
  }, [contact.data]);

  const linkResult = params.get('email');
  useEffect(() => {
    if (linkResult === 'confirmed') {
      setNotice('Email confirmed. Appointment emails will go to this address.');
      void queryClient.invalidateQueries({ queryKey: contactKey });
    } else if (linkResult === 'link-expired')
      setError(
        'That confirmation link has expired or is for a different address. Send a new one below.',
      );
    if (linkResult) setParams({}, { replace: true });
  }, [linkResult]);

  async function save() {
    setBusy('save');
    setError('');
    setNotice('');
    try {
      const saved = await api<ContactSettings>(
        '/api/me/contact',
        {
          method: 'PUT',
          body: JSON.stringify({
            email: email.trim() || null,
            email_notifications: enabled,
          }),
        },
        auth,
      );
      queryClient.setQueryData(contactKey, saved);
      setNotice(
        saved.email && !saved.email_verified
          ? `We sent a confirmation link to ${saved.email}. Open it to start getting appointment emails.`
          : 'Saved.',
      );
    } catch (cause) {
      setError(humanError(cause));
    } finally {
      setBusy(null);
    }
  }

  async function resend() {
    setBusy('resend');
    setError('');
    try {
      await api('/api/me/contact/resend', { method: 'POST' }, auth);
      setNotice(`We sent a new confirmation link to ${contact.data?.email}.`);
    } catch (cause) {
      setError(humanError(cause));
    } finally {
      setBusy(null);
    }
  }

  const current = contact.data;
  const dirty =
    !!current &&
    ((current.email ?? '') !== email.trim() ||
      current.email_notifications !== enabled);

  return (
    <>
      <PageHeader
        eyebrow="Account"
        title="Email & reminders"
        description="Get a confirmation when you book, a reminder the day before and two hours before, and a notice if a visit is cancelled."
      />
      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_290px]">
        <div className="space-y-6">
          <Card title="Appointment emails">
            {contact.isPending ? (
              <LoadingRows rows={2} />
            ) : (
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  void save();
                }}
              >
                <label className="field-label" htmlFor="email">
                  Email address
                </label>
                <div className="flex flex-wrap items-center gap-3">
                  <input
                    id="email"
                    type="email"
                    autoComplete="email"
                    className="field max-w-sm flex-1"
                    placeholder="you@example.com"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                  />
                  {current?.email &&
                    current.email === email.trim() &&
                    (current.email_verified ? (
                      <Badge tone="green">
                        <CheckCircle2 size={12} aria-hidden="true" />
                        Confirmed
                      </Badge>
                    ) : (
                      <Badge tone="amber">
                        <MailWarning size={12} aria-hidden="true" />
                        Waiting for confirmation
                      </Badge>
                    ))}
                </div>
                <label className="mt-5 flex items-start gap-3 text-[13px]">
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={enabled}
                    onChange={(event) => setEnabled(event.target.checked)}
                  />
                  <span>
                    <span className="font-medium">
                      Email me about my appointments
                    </span>
                    <span className="block text-muted">
                      Confirmations, reminders and cancellations. Emails never
                      include symptoms, test results or your doctor&apos;s
                      specialty.
                    </span>
                  </span>
                </label>
                <div className="mt-5 space-y-3">
                  <ErrorNotice message={error} />
                  {notice && (
                    <p
                      role="status"
                      className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[13px] text-emerald-900"
                    >
                      {notice}
                    </p>
                  )}
                </div>
                <div className="mt-5 flex flex-wrap gap-2">
                  <Button busy={busy === 'save'} disabled={!dirty}>
                    Save
                  </Button>
                  {current?.email &&
                    !current.email_verified &&
                    current.email === email.trim() && (
                      <Button
                        type="button"
                        variant="secondary"
                        busy={busy === 'resend'}
                        onClick={() => void resend()}
                      >
                        <Mail size={14} aria-hidden="true" />
                        Send confirmation link again
                      </Button>
                    )}
                </div>
              </form>
            )}
          </Card>
          <Card title="Emails sent to you" bodyClassName="">
            {messages.isPending ? (
              <LoadingRows rows={3} />
            ) : (
              <MessagesTable
                messages={messages.data ?? []}
                showPatient={false}
              />
            )}
          </Card>
        </div>
        <aside className="space-y-5">
          <div className="panel p-5">
            <p className="eyebrow mb-3">Signed in as</p>
            <p className="text-sm font-semibold">{me.name}</p>
            <p className="mt-1 text-[12px] text-muted">{me.phone}</p>
          </div>
          <PrivacyNote>
            We only email an address you&apos;ve confirmed, so a typo never
            sends your appointment details to someone else.
          </PrivacyNote>
        </aside>
      </div>
    </>
  );
}
