import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, test, vi } from 'vitest';
import { api } from '../../api/client';
import { SettingsPage } from './SettingsPage';

vi.mock('../../api/client', () => ({ api: vi.fn() }));
vi.mock('../../auth/AuthProvider', () => ({
  useAuth: () => ({
    auth: { user_id: 'u', role: 'patient', acting_for_patient_id: 'p' },
    me: { name: 'Asha Verma', phone: '+9198 ••••• 001' },
  }),
}));
afterEach(cleanup);

function renderPage() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test('adding an email asks the patient to confirm it before anything is sent', async () => {
  let contact = {
    email: null as string | null,
    email_verified: false,
    email_notifications: true,
  };
  vi.mocked(api).mockImplementation(async (path, options) => {
    if (path === '/api/me/contact' && options?.method === 'PUT') {
      contact = { ...contact, email: JSON.parse(String(options.body)).email };
      return contact;
    }
    if (path === '/api/me/contact') return contact;
    return [];
  });
  renderPage();
  const user = userEvent.setup();
  await user.type(
    await screen.findByLabelText('Email address'),
    'asha@example.com',
  );
  await user.click(screen.getByRole('button', { name: 'Save' }));
  expect(await screen.findByRole('status')).toHaveTextContent(
    'We sent a confirmation link to asha@example.com',
  );
  expect(screen.getByText('Waiting for confirmation')).toBeInTheDocument();
  expect(
    screen.getByRole('button', { name: /Send confirmation link again/ }),
  ).toBeInTheDocument();
});

test('lists the emails sent, and explains the ones that were not', async () => {
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === '/api/me/contact')
      return {
        email: 'asha@example.com',
        email_verified: true,
        email_notifications: true,
      };
    return [
      {
        notification_id: '1',
        kind: 'appointment_booked',
        channel: 'email',
        status: 'sent',
        send_after: '2026-11-03T10:00:00Z',
        sent_at: '2026-11-03T10:00:05Z',
        recipient: 'as•••@example.com',
        subject: 'Appointment confirmed',
        detail: null,
        attempts: 1,
        created_at: '2026-11-03T10:00:00Z',
        starts_at: '2026-11-09T09:45:00Z',
        patient_name: 'Asha Verma',
        doctor_name: 'Nikhil Patel',
        on_hold: null,
      },
      {
        notification_id: '2',
        kind: 'appointment_reminder_24h',
        channel: 'email',
        status: 'cancelled',
        send_after: '2026-11-08T09:45:00Z',
        sent_at: null,
        recipient: null,
        subject: null,
        detail: 'appointment cancelled',
        attempts: 0,
        created_at: '2026-11-03T10:00:00Z',
        starts_at: '2026-11-09T09:45:00Z',
        patient_name: 'Asha Verma',
        doctor_name: 'Nikhil Patel',
        on_hold: null,
      },
    ];
  });
  renderPage();
  expect(await screen.findByText('Booking confirmation')).toBeInTheDocument();
  expect(screen.getByText('Confirmed')).toBeInTheDocument();
  expect(screen.getByText('Reminder, 1 day before')).toBeInTheDocument();
  expect(screen.getAllByText('Appointment cancelled').length).toBeGreaterThan(
    0,
  );
});
