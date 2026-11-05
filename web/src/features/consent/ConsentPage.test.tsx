import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';
import { api } from '../../api/client';
import { ConsentPage } from './ConsentPage';

vi.mock('../../api/client', () => ({ api: vi.fn() }));
vi.mock('../../auth/AuthProvider', () => ({
  useAuth: () => ({
    auth: {
      user_id: 'u-asha',
      role: 'patient',
      acting_for_patient_id: 'p-asha',
    },
  }),
}));

afterEach(cleanup);

const later = new Date(Date.now() + 30 * 86_400_000).toISOString();

test('only consents on your own record can be revoked', async () => {
  vi.mocked(api).mockResolvedValue([
    {
      consent_id: 'mine',
      patient_id: 'p-asha',
      grantee_user_id: 'u-rohan',
      scope: ['records:read'],
      purpose: 'second opinion',
      expires_at: later,
      revoked_at: null,
      patient_name: 'Asha Verma',
      grantee_name: 'Rohan Reddy',
    },
    {
      consent_id: 'theirs',
      patient_id: 'p-lata',
      grantee_user_id: 'u-asha',
      scope: ['records:read'],
      purpose: 'family care',
      expires_at: later,
      revoked_at: null,
      patient_name: null,
      grantee_name: 'Asha Verma',
    },
  ]);
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ConsentPage />
    </QueryClientProvider>,
  );
  const shared = (await screen.findByText('Rohan Reddy')).closest('article')!;
  expect(within(shared).getByText('Can see your records')).toBeInTheDocument();
  expect(
    within(shared).getByRole('button', { name: /Revoke access/ }),
  ).toBeInTheDocument();

  const incoming = screen.getByText('Another patient').closest('article')!;
  expect(
    within(incoming).getByText('Shared their records with you'),
  ).toBeInTheDocument();
  expect(
    within(incoming).queryByRole('button', { name: /Revoke/ }),
  ).not.toBeInTheDocument();
});

test('a patient shares access by mobile number', async () => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockResolvedValue([]);
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ConsentPage />
    </QueryClientProvider>,
  );
  const user = userEvent.setup();
  const share = screen.getByRole('button', { name: /Share access/ });
  expect(share).toBeDisabled();
  await user.type(screen.getByLabelText('Mobile number'), '98200 00009');
  await user.click(screen.getByRole('button', { name: '1 month' }));
  await user.click(share);
  expect(vi.mocked(api)).toHaveBeenCalledWith(
    '/api/consents/share',
    {
      method: 'POST',
      body: JSON.stringify({
        phone: '98200 00009',
        scope: ['records:read'],
        purpose: 'Family care',
        days: 30,
      }),
    },
    expect.objectContaining({ role: 'patient' }),
  );
  expect(await screen.findByRole('status')).toHaveTextContent(
    'Shared with 98200 00009',
  );
});
