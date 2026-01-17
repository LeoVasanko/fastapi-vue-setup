/**
 * FastAPI-Vue Vite Plugin
 *
 * Configures Vite for FastAPI backend integration:
 * - Proxies /api/* requests to the FastAPI backend
 * - Builds to the Python module's frontend-build directory
 *
 * Environment variables (with defaults):
 *   FASTAPI_VUE_BACKEND_URL=http://localhost:5180 - Backend API URL for proxying
 */

const backendUrl = process.env.FASTAPI_VUE_BACKEND_URL || "http://localhost:5180"

export default function fastapiVue({ paths = ["/api"] } = {}) {
  // Build proxy configuration for each path
  const proxy = {}
  for (const path of paths) {
    proxy[path] = {
      target: backendUrl,
      changeOrigin: false,
      ws: true,
    }
  }

  return {
    name: "fastapi-vite",
    config: () => ({
      server: { proxy },
      build: {
        outDir: "../MODULE_NAME/frontend-build",
        emptyOutDir: true,
      },
    }),
  }
}
