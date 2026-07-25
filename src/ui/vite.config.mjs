import { defineConfig, createLogger } from 'vite'
import react from '@vitejs/plugin-react'

// Vite attaches its own `error` handler to the proxy EventEmitter after the
// user's `configure` runs, so `proxy.on('error', ...)` can't suppress the
// "ws proxy error" / "ws proxy socket error" messages; the socket-level
// error is per-request and unreachable from config entirely. The only lever
// is the logger. These errors fire when a browser socket tears down
// mid-write (HMR reload, StrictMode remount, backgrounded tab) — the
// frontend reconnects on its own.
const logger = createLogger()
const originalError = logger.error.bind(logger)
logger.error = (msg, options) => {
  if (typeof msg === 'string' && /ws proxy (?:socket )?error/.test(msg)) {
    return
  }
  originalError(msg, options)
}

export default defineConfig({
  customLogger: logger,
  plugins: [react()],
  base: '/',
  optimizeDeps: {
    // Pre-bundle the heavy charting stack at startup so vite doesn't discover
    // and re-optimize it mid-session. echarts (+ its transitive zrender) is
    // large; a lazy re-optimize pass restarts vite's module server and, on
    // vite 8, briefly 404s `Sec-Fetch-Dest: script` requests — so a browser
    // loading the dashboard during that window white-screens (never renders).
    // Declaring them here makes the optimize happen once, up front. See #10494.
    include: ['html2canvas', 'echarts', 'echarts-for-react']
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    rollupOptions: {
      output: {
        assetFileNames: 'assets/[name].[hash][extname]',
        chunkFileNames: 'assets/[name].[hash].js',
        entryFileNames: 'assets/[name].[hash].js'
      }
    }
  },
  server: {
    port: 5556,
    proxy: {
      '/api': 'http://localhost:5555',
      '/ws': {
        target: 'ws://localhost:5555',
        ws: true,
      }
    }
  }
})
