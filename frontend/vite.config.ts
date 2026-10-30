import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: { manifest: true, outDir: 'dist', assetsDir: 'assets/ui', sourcemap: false },
  server: {
    proxy: Object.fromEntries(['/backend', '/config', '/uploads', '/assets/avatars', '/assets/images'].map(path => [path, {
      target: 'https://127.0.0.1:18443', secure: false, changeOrigin: true,
    }])),
  },
});
