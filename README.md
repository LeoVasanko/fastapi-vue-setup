# fastapi-vue-setup

Tool to create or patch FastAPI project with a Vue frontend, with integrated build and development systems. The Python package will not need any JS runtime because it includes a prebuilt Vue frontend in it. For development (Vite and FastAPI auto reloads) and building the package one of npm, deno or bun is required (npm recommended due to bugs in deno and bun).

## Features

- **No JavaScript**: Your Python package can be installed and used without any JS runtime
- **Integrated build system**: Vue frontend builds into Python package during `uv build`
- **Development server**: Single command runs Vite + FastAPI with hot-reload
- **Optimized static serving**: Caching, zstd compression and SPA support

## Installation

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```sh
uv tool install fastapi-vue-setup
fastapi-vue-setup --help
```

Or run directly:

```sh
uvx fastapi-vue-setup my-app
```

## Usage

The script may be used to create an all new project folder or to patch or update an existing project to use this framework. It autodetects the project folder given and performs the appropriate actions.

### Create a new project

```sh
fastapi-vue-setup my-app
```

This will:

1. Run `uv init my-app`
2. Run `create-vue frontend` (interactive - choose your Vue options)
3. Patch the project with FastAPI integration
4. Install dependencies via `uv add`

### Patch an existing project

You should have your pyproject.toml at the current working directory, and Vue with its package.json under `frontend/`. If either one is missing, new applications will be initialised. Otherwise we only patch what can be patched without breaking your existing projects.

```sh
fastapi-vue-setup .
```

### CLI Options

```
fastapi-vue-setup [project-dir] [options]

Options:
  --module-name NAME    Python module name (auto-detected from pyproject.toml)
  --dry-run             Preview changes without modifying files
```

## Port Configuration

The tool uses three distinct ports:

| Port | Purpose               | Used by                        |
| ---- | --------------------- | ------------------------------ |
| 5173 | Vite dev server (HMR) | `npm run dev` via devserver.py |
| 5180 | FastAPI in dev mode   | uvicorn via devserver.py       |
| 5080 | Production server     | `uv run my-app`                |

In development, you access the app at `http://localhost:5173`. Vite proxies `/api/*` requests to FastAPI at port 5180. Configurable with `devserver.py` arguments.

In production, FastAPI serves both the API and static files at `http://localhost:5080`. Configurable by `host:port` argument.

## Vite Plugin Configuration

The `fastapiVue()` plugin in `vite.config.ts` accepts options to customize proxy behavior:

```js
import fastapiVue from "./vite-plugin-fastapi.js";

export default defineConfig({
  plugins: [
    vue(),
    // Default: proxies only /api
    fastapiVue(),

    // Or specify custom paths to proxy to backend
    fastapiVue({ paths: ["/api", "/auth", "/ws"] }),
  ],
});
```

The plugin reads environment `FASTAPI_VUE_BACKEND_URL` (default: `http://localhost:5180`) to determine where to proxy requests. This is set automatically by `devserver.py`.

## Project Structure

After patching, your project will have:

```
my-app/
├── frontend/                # Vue application
│   ├── src/
│   ├── vite.config.ts       # Builds to ../my_app/frontend-build
│   └── package.json
├── my_app/                  # Python package
│   ├── __init__.py
│   ├── __main__.py          # CLI entry point
│   ├── app.py               # FastAPI application
│   └── frontend-build/      # Built frontend (gitignored)
├── scripts/
│   ├── devserver.py         # Development server
│   └── fastapi-vue/         # Build utilities
└── pyproject.toml           # Project configuration
```

The script finds your existing fastpi app module and other files and patches them with minimal changes to enable the Vue-FastAPI interconnection.

## Development Workflow

```bash
# Start dev server (runs both Vite and FastAPI)
uv run scripts/devserver.py

# Build for production
uv build

# Run production server
uv run my-app
```

# Frontend serving

Your FastAPI app will use [fastapi-vue](https://git.zi.fi/LeoVasanko/fastapi-vue) to serve the frontend file. Refer to that package's documentation for further configuration.
