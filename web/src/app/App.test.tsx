import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { api } from '../api/client';
import { AuthProvider } from '../auth/AuthProvider';
import { App } from './App';

vi.mock('../api/client', async (original) => ({
  ...(await original<typeof import('../api/client')>()),
  api: vi.fn(async (path: string) =>
    path.startsWith('/api/ops/metrics')
      ? {
          window_hours: 24,
          runs: [],
          slowest_nodes: [],
          models: [],
          cost_per_run: {},
          cost_formula: '',
        }
      : [],
  ),
}));

beforeEach(() => window.localStorage.clear());
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

test('opens straight into the patient workspace, no login page', async () => {
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

test('switching profile changes the workspace and is remembered', async () => {
  renderApp();
  const user = userEvent.setup();
  await user.click(screen.getAllByRole('button', { name: /Asha Verma/ })[0]);
  await user.click(screen.getByRole('menuitemradio', { name: /Compliance/ }));
  expect(
    within(sidebar()).getByRole('link', { name: 'Audit log' }),
  ).toBeInTheDocument();
  expect(
    within(sidebar()).queryByRole('link', { name: 'Care assistant' }),
  ).not.toBeInTheDocument();
  expect(window.localStorage.getItem('medpal.profile')).toBe('compliance');
  expect(vi.mocked(api)).toHaveBeenCalledWith(
    expect.stringContaining('/api/ops/metrics'),
    {},
    expect.objectContaining({ role: 'compliance' }),
  );
});

test('a page outside the current role redirects home', async () => {
  window.localStorage.setItem('medpal.profile', 'desk');
  renderApp('/audit');
  expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent(
    'Clinic operations',
  );
});
