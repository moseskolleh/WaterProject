import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // Relative asset URLs so the same build works when Streamlit serves the
  // bundle from the component's static directory.
  base: './',
  build: { outDir: 'dist', assetsDir: 'assets' },
});
