import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/triage': 'http://localhost:8000',
    },
  },
  test: { environment: 'jsdom', setupFiles: './src/test.setup.ts' },
});
