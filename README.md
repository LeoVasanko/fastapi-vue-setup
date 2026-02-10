# fastapi-vue-setup

Create or patch a FastAPI + Vue project with an integrated dev/build workflow.

- Development: one command runs Vite + FastAPI (reloads)
- Production: `uv build` bakes the built Vue assets into the Python package (no Node/JS runtime needed to *run* the installed package)

## Quick start

Install [UV](https://docs.astral.sh/uv/) and any JS runtime (node, deno, or bun).

This README uses `my-app` as the example project name:

- project directory: `my-app/`
- Python module: `my_app`
- env prefix: `MY_APP`
- CLI command: `my-app`

Create a new project in `./my-app`:

```sh
uvx fastapi-vue-setup my-app
```

Once in your source tree, you will typically use `.` for the path. If there is an existing project, `fastapi-vue-setup` will do its best to find and patch a backend module and create or patch a Vue project in `frontend/`. The integration can be upgraded by running a new version of `fastapi-vue-setup` on it, preserving earlier default ports and user customizations.

## In your project

ℹ️ Everything below is meant to be run within your project source tree.

The setup creates a CLI entry for your package, so that it becomes a command to run, not a Python module nor `fastapi myapp...`. The CLI main can be customized, although --listen should be kept for devserver compatibility.

You can choose the JS runtime with environment `JS_RUNTIME` (e.g. `node`, `deno`, `bun`, or path to one). This is used by the build and the devserver scripts. By default any available runtime on the system is chosen.

### Development server (Vite + FastAPI)

```sh
uv run scripts/devserver.py [args]
```

ℹ️ Arguments are forwarded to the main CLI, except that `--listen` controls where Vite listens, and `--backend` is passed to main CLI as `--listen`.

### Production

Build the Python package (this compiles the Vue frontend) and run the production server:

```sh
uv build && uv run my-app [args]
```

Once happy with it, publish the package

```sh
uv build && uv publish
```

Afterwards, you can easily run it anywhere, no JS runtimes required:

```sh
uvx my-app [args]
```

ℹ️ Instead of `uvx` you may consider `uv tool install`, oldskool `pip install` or whatever best suits you.

### Vite plugin

The generated Vite plugin lives in `frontend/vite-plugin-fastapi.js` and defaults to proxying `/api`.

It reads `MY_APP_BACKEND_URL` to know where to proxy; if unset it falls back to your configured default backend port.

## Project layout (typical)

```
my-app/
├── frontend/                    # Vue app (Vite)
│   ├── src/
│   ├── vite-plugin-fastapi.js
│   └── package.json
├── my_app/                      # Python package
│   ├── __main__.py              # CLI entrypoint
│   ├── app.py                   # FastAPI app
│   └── frontend-build/          # built assets (included in distributions)
├── pyproject.toml
└── scripts/
    ├── devserver.py             # Run Vite and FastAPI together in dev mode
    └── fastapi-vue/             # Dev utilities (only on the source tree)
        ├── build-frontend.py
        ├── buildutil.py
        └── devutil.py
```

## The fastapi-vue runtime module

The backend runs the FastAPI app and serves the frontend build using the companion package in [fastapi-vue/README.md](fastapi-vue/README.md). Your project will depend on Fastapi and this lightweight module.

ℹ️ Development functionality is in `scripts/fastapi-vue/` directly in your source tree, and is not to be confused with this runtime module. Only the runtime is installed with your package.
