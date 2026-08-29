import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    // Phase 1: only /api/health is backed by a real endpoint. The proxy exists so
    // the frontend can call the API on a same-origin path in every environment.
    // 127.0.0.1 rather than localhost: on macOS localhost resolves to ::1 first,
    // which uvicorn's default IPv4 bind does not answer.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
