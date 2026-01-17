# fastapi-vue-setup

Tool to create or patch FastAPI project with a Vue frontend, with integrated build and development systems. The Python package will not need any JS runtime because it includes a prebuilt Vue frontend in it. For development (Vite and FastAPI auto reloads) and building the package one of npm, deno or bun is required (node is recommended due to bugs in deno and bun).

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

In development, you access the Vite dev server at `http://localhost:5173`. Vite proxies `/api/*` requests to FastAPI at port 5180. Ports and hosts of Vite and FastAPI are configurable by `devserver.py` arguments.

In production, FastAPI serves both the API and static files at `http://localhost:5080`. Configurable by `host:port` argument with defaults set in `__main__.py`

## Main CLI

If your project didn't already have `__main__.py`, we create one that runs the FastAPI app with richer configuration than what the FastAPI CLI offers. Running your module starts it in production mode, and optionally host:port may be given as argument to specify where it listens.

If you are running behind a reverse proxy like [Caddy](https://caddyserver.com/) on localhost, your app will trust the proxy headers it sends. However, if you need to configure another proxy host or IP, set `FORWARDED_ALLOW_IPS` env variable before running the server.

The devserver script depends on this CLI entry for running the backend. You will have to modify the `devserver.py` script if your app has its own incompatible main module. Note that we set FastAPI debug mode and Uvicorn reload when configured via `FASTAPI_VUE_BACKEND_URL` env variable (set by `devserver.py`), while for normal production use these stay disabled. The same variable also controls static files serving (disabled in dev mode).


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

```
my-app/
├── frontend/                 # Vue application
│   ├── src/
│   ├── vite-plugin-fastapi.js
│   ├── vite.config.js
│   └── package.json
├── my_app/                   # Python module (files included in sdist)
│   ├── __init__.py
│   ├── __main__.py           # CLI entrypoint
│   ├── app.py                # FastAPI application
│   └── frontend-build/       # Built frontend (gitignored)
├── scripts/
│   ├── devserver.py          # CLI dev server (only in source tree)
│   └── fastapi-vue/
│       ├── build-frontend.py
│       └── util.py
└── pyproject.toml
```

The project directory tree looks roughly like this after project creation or patching. The script finds your existing app module and other files and patches them with minimal changes to enable the Vue-FastAPI interconnection. New Python and Vue projects are created automatically if none exist.

## Development Workflow

```bash
# Start dev server (runs both Vite and FastAPI)
uv run scripts/devserver.py

# Build for production
uv build

# Run production server
uv run my-app
```

## Frontend serving

Your FastAPI app will use [fastapi-vue](https://git.zi.fi/LeoVasanko/fastapi-vue) to serve the frontend files. Refer to that package's documentation for further configuration.
