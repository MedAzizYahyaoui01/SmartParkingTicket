import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // One .env at the repo root for the whole project; only VITE_* values reach the browser.
  envDir: '..',
  // IPv4 on a fixed port: "localhost" may resolve to 127.0.0.1 only, and the API's CORS
  // list allows exactly http://localhost:5173 (fail loudly if the port is taken).
  server: { host: '127.0.0.1', port: 5173, strictPort: true },
})
