import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
      },
      '/command': 'http://127.0.0.1:8000',
      '/status': 'http://127.0.0.1:8000',
      '/user': 'http://127.0.0.1:8000',
    },
  },
});
