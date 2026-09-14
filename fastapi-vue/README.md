# FastAPI-Vue Runtime

Runtime utilities for making FastAPI apps standalone, with their own CLI entry point and facilities that make the FastAPI + Vue stack pleasant to use.

ℹ️ Use [fastapi-vue-setup](https://pypi.org/project/fastapi-vue-setup/) to set up your project. Everything below is configured automatically by it.

## Main Components

- **Frontend**: Serves static files with proper caching, compression and SPA support
- **Server**: Runs the FastAPI app from your own CLI entry point with uvicorn facilities vastly augmented

## Quickstart

Serve built frontend assets from `frontend-build/`:

```python
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi_vue import Frontend

frontend = Frontend(Path(__file__).with_name("frontend-build"), spa=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await frontend.load()
    yield

app = FastAPI(lifespan=lifespan)

# Add API routes here...

# Final catch-all route for frontend files (keep at end of file)
frontend.route(app, "/")
```

If SPA mode is disabled, we only route the paths that actually exist, leaving anything else to your own handlers that come after and may themselves wish to catch all that remains.

## Frontend (fastapi_vue.Frontend)

- Designed to serve at `/`, living together with your other routes
- SPA routing: serves `index.html` for paths not otherwise handled
- RAM caching with zstd compression
- Browser caching with ETag, Last-Modified and immutable assets

With `FastAPI(debug=True)`, frontend requests return HTTP 409 with a message directing you to the Vite dev server. This prevents accidentally serving an outdated frontend build during development.

- `directory`: Path on local filesystem
- `index`: Index file name (default: `index.html`)
- `spa`: Serve index at any path (default: `False`)
- `catch_all`: Register a single catch-all handler instead of a route to each file; default for SPA
- `cached`: Path prefixes treated as immutable (default: `/assets/`)
- `favicon`: Optional path or glob (e.g. `/assets/logo*.png`)
- `zstdlevel`: Compression level (default: 18)

ℹ️ Browsers commonly request `/favicon.ico` even when another icon is specified in HTML. The favicon option lets you serve an SVG or PNG there instead. This also provides a convenient application default that a deployment reverse proxy such as Caddy or Nginx can override with company branding.

## Server runner (fastapi_vue.server)

When you need more flexibility than the `fastapi` CLI provides—for example, to support arguments in your own CLI—you can use the bundled server runner.

It starts the FastAPI app, running directly in the current process when possible and delegating to Uvicorn supervisors for reloads and multiple workers. The `server.run` is modeled after `uvicorn.run` that you would otherwise have to use to run FastAPI.

```python
from fastapi_vue import server

server.run("my_app.app:app", listen=["localhost:8000"])
```

Endpoints are plain strings: `host:port`, a bare port (localhost only), `:port` (all interfaces), or a unix socket path. Multiple endpoints can be served simultaneously. This also avoids Uvicorn's localhost limitation, where localhost may bind only to either 127.0.0.1 or ::1.

A single `reload` argument replaces Uvicorn's separate reload arguments and may directly specify paths to watch.

A startup box with the app name, version and connect URL is printed before serving. Pass a `startup_box` template (`{name}`, `{version}`, `{listen}`, `{url}`, ...) to customize it, None to disable, or use `server.print_startup_box` on its own.

<img src="https://raw.githubusercontent.com/LeoVasanko/fastapi-vue-setup/main/docs/my-app.webp" alt="My App startup box and log items" width="500">

Logging is integrated as well: removes noisy uvicorn logging, replacing it with prettified log formatting, a colored access log and tracebacks rendered by [tracerite](https://pypi.org/project/tracerite/). Note that HTTP responses also include tracerite formatting when `FastAPI(debug=True)` is used.

Other arguments are generally passed to `uvicorn.run`, although some like `log_config` receive our modifications.

> As a deployment option, environment `FORWARDED_ALLOW_IPS` controls `X-Forwarded` trusted IPs (default: `127.0.0.1,::1` works for typical setups).

### Environment (fastapi_vue.env)

We use environment variables to pass values between program components, from devserver script setting dev mode and telling backend and frontend URLs, to your CLI, which in turn runs the FastAPI app that may also need access to this information. The variables are prefixed by the current application name to avoid conflicts. The CLI entry point should set one like `os.environ["FASTAPI_VUE"] = "MY_APP"`, before using `server.run`

The following properties read the environment and return `None` when variables haven't been set:

- `fastapi_vue.env.prefix` — the prefix itself
- `fastapi_vue.env.dev` — running in development mode, from e.g. `MY_APP_DEV=1`
- `fastapi_vue.env.vite_url`, `fastapi_vue.env.backend_url` — URLs set by the devserver
