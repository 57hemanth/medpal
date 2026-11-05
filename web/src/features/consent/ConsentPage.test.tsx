import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
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
