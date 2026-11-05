import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { expect, test, vi } from 'vitest';
import { api } from '../../api/client';
import { TriagePage } from './TriagePage';

vi.mock('../../api/client', () => ({ api: vi.fn() }));
vi.mock('../../auth/AuthProvider', () => ({
  useAuth: () => ({
    auth: {
      user_id: 'patient',
      role: 'patient',
      acting_for_patient_id: 'patient',
    },
  }),
}));

test('keeps a booking retry idempotent and disables completed appointment choices', async () => {
  const requests: { idempotency_key: string }[] = [];
  vi.mocked(api).mockImplementation(async (path, options) => {
    if (path === '/api/appointments') return [];
    if (path === '/triage')
      return {
        thread_id: 'thread',
        status: 'awaiting_choice',
        specialty: 'Orthopaedics',
        candidates: [
          {
            slot_id: 'slot',
            doctor_name: 'Test Doctor',
            clinic_name: 'Test Clinic',
            display_time: 'Mon 9 Nov, 09:00',
          },
        ],
      };
    if (path.endsWith('/resume')) {
      requests.push(JSON.parse(String(options?.body)));
      if (requests.length === 1)
        throw new Error('Connection interrupted. Try again.');
      return {
        thread_id: 'thread',
        status: 'booked',
        booking_id: 'booking-ref',
      };
    }
    throw new Error('Unexpected endpoint');
  });
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <TriagePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const user = userEvent.setup();
  await user.click(
    screen.getByRole('button', { name: 'I’ve had knee pain for a week' }),
  );
  await user.click(await screen.findByRole('button', { name: 'Choose time' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Connection interrupted',
  );
  await user.click(screen.getByRole('button', { name: 'Choose time' }));
  expect(await screen.findByText('Appointment confirmed')).toBeInTheDocument();
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Choose time' })).toBeDisabled(),
  );
  expect(requests).toHaveLength(2);
  expect(requests[0].idempotency_key).toBe(requests[1].idempotency_key);
});
