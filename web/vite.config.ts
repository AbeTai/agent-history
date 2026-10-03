import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Match `agent-history serve --port N` with AGENT_HISTORY_PORT=N npm run dev
      '/api': `http://127.0.0.1:${process.env.AGENT_HISTORY_PORT ?? 8765}`,
    },
  },
  test: {
    environment: 'node',
  },
})
