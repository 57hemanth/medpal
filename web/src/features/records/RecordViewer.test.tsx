import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import { apiFile } from '../../api/client';
import { RecordViewer } from './RecordViewer';

vi.mock('../../api/client', () => ({ apiFile: vi.fn() }));
vi.mock('../../auth/AuthProvider', () => ({
  useAuth: () => ({
    auth: { user_id: 'u', role: 'patient', acting_for_patient_id: 'p' },
  }),
}));

test('opens the record with the viewer identity and closes on Escape', async () => {
  vi.mocked(apiFile).mockResolvedValue(
    new Blob(['LDL 162 mg/dL'], { type: 'text/plain' }),
  );
  const onClose = vi.fn();
  render(<RecordViewer docId="doc-1" title="Lab report" onClose={onClose} />);
  expect(await screen.findByText('LDL 162 mg/dL')).toBeInTheDocument();
  expect(apiFile).toHaveBeenCalledWith(
    '/api/records/doc-1/file',
    expect.objectContaining({ user_id: 'u' }),
  );
  await userEvent.keyboard('{Escape}');
  expect(onClose).toHaveBeenCalled();
});
