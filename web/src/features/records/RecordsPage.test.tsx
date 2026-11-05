import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';
import { api } from '../../api/client';
import { RecordsPage } from './RecordsPage';

vi.mock('../../api/client', () => ({ api: vi.fn() }));
vi.mock('../../auth/AuthProvider', () => ({
  useAuth: () => ({
    auth: { user_id: 'u', role: 'patient', acting_for_patient_id: 'p' },
    me: { name: 'Asha Verma' },
  }),
}));
afterEach(cleanup);

test('a patient deletes a record only after confirming, and it leaves the list', async () => {
  let records = [
    {
      doc_id: 'd1',
      status: 'ready',
      error: null,
      uploaded_at: '2026-11-03T10:00:00Z',
      type: 'lab_report',
      title: 'Lipid profile',
    },
  ];
  const calls: string[] = [];
  vi.mocked(api).mockImplementation(async (path, options) => {
    if (path === '/api/records' && !options?.method) return records;
    if (path === '/api/records/d1' && options?.method === 'DELETE') {
      calls.push('DELETE');
      records = [];
      return null;
    }
    throw new Error(`unexpected ${path}`);
  });
  render(
    <QueryClientProvider client={new QueryClient()}>
      <RecordsPage />
    </QueryClientProvider>,
  );
  const user = userEvent.setup();
  await user.click(
    await screen.findByRole('button', { name: 'Delete Lipid profile' }),
  );
  expect(screen.getByRole('dialog')).toHaveTextContent("can't be undone");
  await user.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(calls).toEqual([]);
  await user.click(
    screen.getByRole('button', { name: 'Delete Lipid profile' }),
  );
  await user.click(screen.getByRole('button', { name: 'Delete record' }));
  await waitFor(() =>
    expect(screen.queryByText('Lipid profile')).not.toBeInTheDocument(),
  );
  expect(calls).toEqual(['DELETE']);
});
