import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { manifest: true, outDir: 'dist', assetsDir: 'assets/ui', sourcemap: false },
  server: {
    proxy: Object.fromEntries(
      ['/api', '/uploads', '/assets/avatars', '/assets/images'].map((path) => [
        path,
        {
          target: 'https://127.0.0.1:18443',
          secure: false,
          changeOrigin: true,
        },
      ]),
    ),
  },
});
