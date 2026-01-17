# fastapi-vue-setup

Tool to create or patch FastAPI project with a Vue frontend, with integrated build and development systems. Only building the package needs JS runtime and Vue. Additionally, a devmode setup using Vite dev server with hot auto reloads is available via the scripts/devserver.py script (only intended to be used on the source repo, not included in installed package).

## Features

- **No JavaScript**: Your Python package can be installed and used without any JS runtime
- **Create new projects** with `uv init` + `create-vue` (interactive)
- **Patch existing projects** with build hooks and dev server scripts
- **Integrated build system**: Vue frontend builds into Python package during `uv build`
- **Development server**: Single command runs Vite + FastAPI with hot-reload
- **Optimized static serving**: zstd compression, ETag caching, SPA support

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

### Create a new project

```sh
fastapi-vue-setup new my-app
```

This will:

1. Run `uv init my-app`
2. Run `npm create vue@latest frontend` (interactive)
3. Patch the project with FastAPI integration

### Patch an existing project

```bash
fastapi-vue-setup patch /path/to/project
```

Options:

- `--module-name NAME`: Python module name (auto-detected from pyproject.toml)
- `--vite-port PORT`: Vite dev server port (default: 5173)
- `--backend-port PORT`: Backend API port in dev mode (default: 5174)
- `--prod-port PORT`: Production server port (default: 8000)
- `--force`: Overwrite existing files
- `--dry-run`: Preview changes without modifying files

### Update an existing project

```bash
fastapi-vue-setup update /path/to/project
```

Same as `patch --force` - overwrites template files with latest versions.

## Port Configuration

The tool uses three distinct ports:

| Port | Purpose               | Used by                        |
| ---- | --------------------- | ------------------------------ |
| 5173 | Vite dev server (HMR) | `npm run dev` via devserver.py |
| 5174 | FastAPI in dev mode   | uvicorn via devserver.py       |
| 8000 | Production server     | `uv run my-app`                |

In development, you access the app at `http://localhost:5173`. Vite proxies `/api/*` requests to FastAPI at port 5174.

In production, FastAPI serves both the API and static files from the same port (8000).

## Project Structure

After patching, your project will have:

```
my-app/
├── frontend/                 # Vue.js application
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

The script finds your existing fastpi app module (even if not named app.py) and other files and patches them with minimal changes to enable the Vue-FastAPI interconnection.

## Development Workflow

```bash
# Start dev server (runs both Vite and FastAPI)
uv run scripts/devserver.py

# Build for production
uv build

# Run production server
uv run my-app
```

## Static File Serving

The `Frontend` class provides:

- **Automatic zstd compression** at level 18
- **Smart caching**: Content-hashed assets get `immutable` cache headers
- **ETag support**: 304 Not Modified responses for cached content
- **SPA routing**: Falls back to index.html for client-side routes
- **Favicon handling**: Automatic /favicon.ico from hashed assets
