/**
 * FastAPI-Vue Vite Plugin
 *
 * Configures Vite for FastAPI backend integration:
 * - Proxies /api/* requests to the FastAPI backend
 * - Builds to the Python module's frontend-build directory
 *
 * Environment variables (with defaults):
 *   VITE_PORT=5173        - Vite dev server port
 *   VITE_BACKEND_URL=http://localhost:5180 - Backend API URL for proxying
 */

const backendUrl =
  process.env.VITE_BACKEND_URL || "http://localhost:{{BACKEND_PORT}}";
const vitePort = parseInt(process.env.VITE_PORT || "{{VITE_PORT}}");

export default {
  name: "fastapi-vite",
  config: () => ({
    server: {
      host: "localhost",
      port: vitePort,
      strictPort: true,
      proxy: {
        "/api": {
          target: backendUrl,
          changeOrigin: false,
          ws: true,
        },
      },
    },
    build: {
      outDir: "../{{MODULE_NAME}}/frontend-build",
      emptyOutDir: true,
    },
  }),
};
