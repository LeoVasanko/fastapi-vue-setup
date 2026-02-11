/**
 * FastAPI-Vue Vite Plugin
 * auto-upgrade@fastapi-vue-setup -- remove this if you edit the plugin
 *
 * Configures Vite for FastAPI backend integration:
 * - Proxies /api/* requests to the FastAPI backend
 * - Builds to the Python module's frontend-build directory
 *
 * Options:
 *   paths - Array of paths to proxy (default: ["/api"])
 */

export default function fastapiVue({ paths = ["/api"] } = {}) {
  const backendUrl = process.env.ENVPREFIX_BACKEND_URL || "http://localhost:TEMPLATE_DEV_PORT"

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
    name: "vite-plugin-fastapi-MODULE_NAME",
    config: () => ({
      server: { proxy },
      build: {
        outDir: "../MODULE_NAME/frontend-build",
        emptyOutDir: true,
      },
    }),
  }
}
