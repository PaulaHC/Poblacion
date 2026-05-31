import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    port: 3000,
    host: '0.0.0.0',
    proxy: {
      // Si tu backend (que habla con Influx + Ollama) corre en otro puerto,
      // ajusta el target. Si está en el mismo contenedor, elimina el proxy.
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
