import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import { api } from '../../api/client';
import { ScribePage } from './ScribePage';

vi.mock('../../api/client', () => ({ api: vi.fn() }));
vi.mock('../../auth/AuthProvider', () => ({
  useAuth: () => ({
    auth: { user_id: 'doc', role: 'doctor', acting_for_patient_id: null },
  }),
}));

const review = {
  thread_id: 'scribe-thread',
  status: 'awaiting_review',
  soap: {
    subjective: 'Chest tightness on stairs.',
    objective: 'BP 138/86.',
    assessment: 'As stated by the doctor.',
    plan: 'Atorvastatin 10 mg at night.',
    medicines: ['Atorvastatin', 'Metformin'],
  },
  medicines: ['Atorvastatin', 'Metformin'],
  stock_flags: [
    { medicine: 'Atorvastatin', status: 'in_stock', qty: 40, as_of: null },
    {
      medicine: 'Metformin',
      status: 'out_of_stock',
      qty: 0,
      as_of: null,
      alternatives: [
        {
          medicine: 'Glyciphage',
          kind: 'same_composition',
          available: 12,
          clinic: null,
        },
        {
          medicine: 'Metformin',
          kind: 'other_clinic',
          available: 30,
          clinic: 'Aundh Clinic',
        },
      ],
    },
  ],
  rejected_medicines: ['Rosuvastatin'],
  drafting_unavailable: false,
  signed: null,
};

test('doctor picks a consultation, reviews stock-flagged draft, edits and signs', async () => {
  const resumed: { action: string; soap?: { plan: string } }[] = [];
  vi.mocked(api).mockImplementation(async (path, options) => {
    if (path === '/api/scribe/consultations')
      return [
        {
          appt_id: 'appt-1',
          starts_at: '2026-11-09T09:00:00+05:30',
          clinic_name: 'Baner Clinic',
          patient_name: 'Asha Verma',
          encounter_id: null,
          signed: false,
        },
      ];
    if (path === '/api/scribe/encounters') return { encounter_id: 'enc-1' };
    if (path === '/api/scribe/sessions') return review;
    if (path.endsWith('/resume')) {
      resumed.push(JSON.parse(String(options?.body)));
      return {
        ...review,
        status: 'signed',
        signed: { note_id: 'note-1', version: 1, content_hash: 'abc123' },
      };
    }
    throw new Error(`Unexpected endpoint ${path}`);
  });
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <ScribePage />
    </QueryClientProvider>,
  );
  const user = userEvent.setup();
  const generate = screen.getByRole('button', { name: /generate soap draft/i });
  await user.type(
    screen.getByLabelText('What was discussed?'),
    'Doctor: start atorvastatin 10 mg at night, continue metformin.',
  );
  expect(generate).toBeDisabled(); // no consultation chosen yet

  await user.click(
    await screen.findByRole('button', { name: 'Start consultation' }),
  );
  await user.click(generate);

  expect(
    await screen.findByText('In stock · 40 available'),
  ).toBeInTheDocument();
  expect(screen.getByText('Out of stock')).toBeInTheDocument();
  expect(screen.getByText(/Rosuvastatin/)).toBeInTheDocument();
  // Out of stock: alternatives are listed; the doctor chooses, nothing is swapped automatically.
  expect(screen.getByText('Aundh Clinic')).toBeInTheDocument();
  expect(screen.getAllByRole('button', { name: 'Use instead' })).toHaveLength(
    1,
  );
  await user.click(screen.getByRole('button', { name: 'Use instead' }));
  expect(
    (screen.getByLabelText('Medicines (comma separated)') as HTMLInputElement)
      .value,
  ).toContain('Glyciphage');

  const plan = screen.getByLabelText('plan');
  await user.clear(plan);
  await user.type(plan, 'Atorvastatin 10 mg at night; review in 2 weeks.');
  await user.click(screen.getByRole('button', { name: /sign note/i }));

  expect(
    await screen.findByText('Note signed and saved with its prescriptions.'),
  ).toBeInTheDocument();
  expect(resumed).toHaveLength(1);
  expect(resumed[0].action).toBe('sign');
  expect(resumed[0].soap?.plan).toBe(
    'Atorvastatin 10 mg at night; review in 2 weeks.',
  );
  expect(resumed[0].soap?.medicines).toEqual(['Atorvastatin', 'Glyciphage']);
});
