import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    port: 3000,
    host: '0.0.0.0',
    // El navegador entra directo por http://localhost:3000.
    // Vite proxya /api hacia el backend por la red interna de Docker.
    proxy: {
      '/api': {
        target: process.env.VITE_BACKEND || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
});