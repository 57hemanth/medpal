import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, test } from 'vitest';
import { AuthProvider } from '../auth/AuthProvider';
import { App } from './App';

test('renders the test login page', () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <AuthProvider>
        <MemoryRouter>
          <App />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );

  expect(screen.getByText(/^MedPal/)).toBeInTheDocument();
  expect(
    screen.getByRole('heading', { name: 'Choose a test login' }),
  ).toBeInTheDocument();
});
