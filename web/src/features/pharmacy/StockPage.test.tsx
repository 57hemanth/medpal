import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';
import { api } from '../../api/client';
import { StockPage } from './StockPage';

vi.mock('../../api/client', () => ({ api: vi.fn() }));
vi.mock('../../auth/AuthProvider', () => ({
  useAuth: () => ({
    auth: { user_id: 'ph', role: 'pharmacist', acting_for_patient_id: null },
    me: { name: 'Pharmacy' },
  }),
}));
afterEach(cleanup);

test('a delivery needs a reason, shows the new count, and is sent as a stock change', async () => {
  const sent: unknown[] = [];
  vi.mocked(api).mockImplementation(async (path, options) => {
    if (path === '/api/pharmacy/stock')
      return [
        {
          medicine_id: 'm1',
          name: 'Clopidogrel',
          composition: 'clopidogrel 75 mg',
          therapeutic_class: null,
          pack_size: null,
          qty: 4,
          as_of: new Date().toISOString(),
          reserved: 1,
          available: 3,
          demand: 2,
          unmet: 0,
          status: 'low',
        },
      ];
    if (path === '/api/pharmacy/stock/history') return [];
    if (path === '/api/pharmacy/stock/m1') {
      sent.push(JSON.parse(String(options?.body)));
      return { medicine_id: 'm1', qty: 14 };
    }
    throw new Error(`unexpected ${path}`);
  });
  render(
    <QueryClientProvider client={new QueryClient()}>
      <StockPage />
    </QueryClientProvider>,
  );
  const user = userEvent.setup();
  await user.click(
    await screen.findByRole('button', { name: 'Update stock of Clopidogrel' }),
  );
  await user.click(screen.getByRole('tab', { name: 'Delivery' }));
  await user.type(screen.getByLabelText('Packs received'), '10');
  expect(screen.getByText('4 → 14')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Save change' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('reason');
  await user.type(screen.getByLabelText('Reason'), 'Invoice 4521');
  await user.click(screen.getByRole('button', { name: 'Save change' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  expect(sent).toEqual([{ kind: 'delivery', qty: 10, reason: 'Invoice 4521' }]);
});
