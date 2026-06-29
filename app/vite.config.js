import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    port: 3000,
    host: '0.0.0.0',
    // El navegador llega por HTTPS a través del proxy Caddy (https://localhost).
    // El WebSocket de HMR debe usar wss y el puerto público 443, no el 3000
    // interno del contenedor.
    hmr: {
      protocol: 'wss',
      clientPort: 443,
    },
    proxy: {
      // En producción el proxy Caddy enruta /api directamente al backend, así
      // que este proxy de Vite solo se usa si arrancas el front en local sin
      // Caddy (vite dev directo contra el backend).
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