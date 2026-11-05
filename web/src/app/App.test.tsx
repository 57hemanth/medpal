import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { type Me, type Role, api } from '../api/client';
import { AuthProvider } from '../auth/AuthProvider';
import { App } from './App';

type MeState = Me | null;
let me: MeState = null;
const asha = (role: Role = 'patient'): Me => ({
  user_id: 'u-asha',
  role,
  acting_for_patient_id: 'p-asha',
  name: 'Asha Verma',
  phone: '+91 98•••••001',
  roles: ['patient', 'caregiver'],
});

vi.mock('../api/client', async (original) => ({
  ...(await original<typeof import('../api/client')>()),
  api: vi.fn(async (path: string, options: RequestInit = {}) => {
    if (path === '/api/me') {
      if (!me) throw new Error('401');
      return me;
    }
    if (path === '/api/auth/role') {
      me = { ...me!, role: JSON.parse(String(options.body)).role };
      return { ok: true };
    }
    if (path === '/api/auth/logout') {
      me = null;
      return { ok: true };
    }
    if (path.startsWith('/api/ops/metrics'))
      return {
        window_hours: 24,
        runs: [],
        slowest_nodes: [],
        models: [],
        cost_per_run: {},
        cost_formula: '',
      };
    return [];
  }),
}));

beforeEach(() => {
  me = null;
  vi.mocked(api).mockClear();
});
afterEach(cleanup);

function renderApp(path = '/') {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <AuthProvider>
        <MemoryRouter initialEntries={[path]}>
          <App />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

const sidebar = () =>
  screen.getAllByRole('navigation', { name: 'Main navigation' })[0];

test('signed out shows mobile sign-in, not the workspace', async () => {
  renderApp();
  expect(
    await screen.findByRole('heading', { name: 'Sign in' }),
  ).toBeInTheDocument();
  expect(screen.getByLabelText('Mobile number')).toBeInTheDocument();
  expect(
    screen.queryByRole('navigation', { name: 'Main navigation' }),
  ).not.toBeInTheDocument();
});

test('a signed-in patient sees their own name and workspace', async () => {
  me = asha();
  renderApp();
  expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent(
    'Asha',
  );
  expect(
    within(sidebar()).getByRole('link', { name: 'Care assistant' }),
  ).toBeInTheDocument();
  expect(
    within(sidebar()).queryByRole('link', { name: 'Audit log' }),
  ).not.toBeInTheDocument();
});

test('the account menu offers only the roles this person holds', async () => {
  me = asha();
  renderApp();
  const user = userEvent.setup();
  await user.click(
    (await screen.findAllByRole('button', { name: /Asha Verma/ }))[0],
  );
  const roles = screen
    .getAllByRole('menuitemradio')
    .map((item) => item.textContent);
  expect(roles).toEqual(['Patient', 'Caregiver']);
  await user.click(screen.getByRole('menuitemradio', { name: /Caregiver/ }));
  expect(vi.mocked(api)).toHaveBeenCalledWith(
    '/api/auth/role',
    expect.objectContaining({ method: 'POST' }),
  );
  expect(
    await within(sidebar()).findByRole('link', { name: 'Shared records' }),
  ).toBeInTheDocument();
});

test('signing out returns to the sign-in page', async () => {
  me = asha();
  renderApp();
  const user = userEvent.setup();
  await user.click(
    (await screen.findAllByRole('button', { name: /Asha Verma/ }))[0],
  );
  await user.click(screen.getByRole('menuitem', { name: 'Sign out' }));
  expect(
    await screen.findByRole('heading', { name: 'Sign in' }),
  ).toBeInTheDocument();
});

test('a page outside the current role redirects home', async () => {
  me = { ...asha('desk'), name: 'Front desk', roles: ['desk'] };
  renderApp('/audit');
  expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent(
    'Clinic operations',
  );
});
