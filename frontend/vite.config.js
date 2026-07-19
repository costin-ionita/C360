import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Forwards /api/* to the FastAPI dev server so the browser only ever talks to
    // one origin (matches how Phase 2+ serves both from the same FastAPI process) --
    // avoids needing CORS handling in frontend code entirely.
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
