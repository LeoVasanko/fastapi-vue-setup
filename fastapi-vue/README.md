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

Other arguments are generally passed to `uvicorn.run`, although some like `log_config` receive our modifications.

### Logging and exceptions

Pretty logging is configured automatically across the host process and all workers, at INFO in development and WARNING in production, with emoji level prefixes, colored access logs, and tracebacks rendered by [tracerite](https://pypi.org/project/tracerite/). With `FastAPI(debug=True)`, **Internal Server Error** responses use tracerite formatting as well.

Application code can simply use `logging.info()` through `logging.exception()`, or ordinary `logging.getLogger("myapp")` loggers, without setting up logging itself. Set any logger's level when part of the application should be quieter or more verbose, for example `log_config={"loggers": {"myapp": {"level": "DEBUG"}}}`, accepting additions and overrides using [Python's logging configuration schema](https://docs.python.org/3/library/logging.config.html#logging-config-dictschema).

## Environment

Environment variables are used to pass values across process boundaries, where ordinary Python variables cannot be shared. We provide runtime passing mainly intended for dev environment passing into the main application CLI, as well as config passing intended for the CLI to pass things to FastAPI side.

Set the application prefix before `server.run()`, at top of your CLI main:

```python
os.environ["FASTAPI_VUE"] = "MY_APP"
```

### Runtime environment

```python
from fastapi_vue import env

env.prefix       # application prefix
env.dev          # development mode (bool)
env.vite_url     # frontend URL (dev)
env.backend_url  # backend URL (dev)
```

The three prefixed variables are set by devserver script and can be read anywhere in your application. Unset values return `None`.

### Teleportation

Mainly intended for passing application config from CLI main to all FastAPI workers and through reloader. Put shared configuration in its own module so that any part of your application can import the same `config` variable:

```python
from dataclasses import dataclass
from fastapi_vue import env

@dataclass
class Config:
    project: str = "."
    read_only: bool = False

config = env(Config)
```

The config values should be set (in CLI main) before teleportation, which occurs in `server.run()` for all registered env objects. Then everyone who imports the object receives those values. Modifications after that point however do not transit to other workers.

Initially the passed in dataclass or msgspec.Struct is constructed with default values to its fields. Any number of env definitions may be added for different things, each getting a prefixed env variable by type name like `MY_APP_CONFIG` above. Beside `server.run`, pass objects to your own processes with `fastapi_vue.teleport()` if needed e.g. from FastAPI app to its workers. The data format in these variables is a JSON object.

### Proxy configuration

You may set `FORWARDED_ALLOW_IPS` to specify which connecting IP addresses are trusted to provide `X-Forwarded-*` headers. This is a server setup option rather than an application setting: the devserver does not set it, and it does not use the application-name prefix. It may therefore be set globally for the whole server. The default `127.0.0.1,::1` works for typical setups where Caddy, Nginx or another frontend server runs on the same machine.
