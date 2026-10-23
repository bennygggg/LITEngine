/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
  build: {
    sourcemap: false,
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        // Cytoscape is only reachable through the lazily-imported canvas map view, so it
        // stays out of the initial route; the rest are stable vendor chunks for caching.
        manualChunks(id) {
          if (id.includes('node_modules/cytoscape')) return 'cytoscape'
          if (id.includes('node_modules/react-markdown') || id.includes('node_modules/remark') ||
              id.includes('node_modules/micromark') || id.includes('node_modules/mdast') ||
              id.includes('node_modules/unified') || id.includes('node_modules/hast')) return 'markdown'
          if (id.includes('node_modules/react-dom') || id.includes('node_modules/react/') ||
              id.includes('node_modules/react-router')) return 'vendor'
          return undefined
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
  },
})
