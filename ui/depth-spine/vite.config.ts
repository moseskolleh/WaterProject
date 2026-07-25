import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { viteSingleFile } from 'vite-plugin-singlefile';

// Two builds from one source:
//
//   build         the Streamlit custom component - separate assets, served
//                 from disk by the Streamlit server, interactive.
//   build:inline  one self-contained page with everything inlined, for
//                 st.components.v1.html in the WebAssembly demo, where there
//                 is no server to serve a component from.
export default defineConfig(({ mode }) => {
  const inline = mode === 'inline';
  return {
    plugins: [react(), ...(inline ? [viteSingleFile()] : [])],
    // Relative asset URLs so the component build works wherever Streamlit
    // mounts it.
    base: './',
    build: {
      outDir: inline ? 'dist-inline' : 'dist',
      assetsDir: 'assets',
      emptyOutDir: true,
      ...(inline
        ? {
            rollupOptions: { input: 'inline.html' },
            assetsInlineLimit: 100_000_000,
            cssCodeSplit: false,
          }
        : {}),
    },
  };
});
