import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, test } from 'vitest';
import { AuthProvider } from '../auth/AuthProvider';
import { App } from './App';

test('renders the MedPal navigation shell', () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <AuthProvider>
        <MemoryRouter>
          <App />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );

  expect(screen.getByRole('heading', { name: 'MedPal' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Records' })).toBeInTheDocument();
});
