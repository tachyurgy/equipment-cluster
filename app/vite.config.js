import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// GH Pages serves project sites at /<repo>/. Override with VITE_BASE if you fork.
const base = process.env.VITE_BASE ?? '/equipment-cluster/'

export default defineConfig({
  base,
  plugins: [react()],
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 1500,
  },
})
