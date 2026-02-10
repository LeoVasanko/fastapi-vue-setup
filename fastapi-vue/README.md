# fastapi-vue

Runtime helpers for FastAPI + Vite/Vue projects.

## Overview

This package provides:

- `fastapi_vue.Frontend`: serves built SPA assets (with SPA support, caching, and optional zstd)
- `fastapi_vue.server.run`: a small Uvicorn runner with convenient `listen` endpoint parsing

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

## Frontend

`Frontend` serves a directory with:

- RAM caching, with zstd compression when smaller than original
- Browser caching: ETag + Last-Modified, Immutable assets
- Favicon mapping (serve PNG or other images there instead)
- SPA routing (serve browsers index.html at all paths not otherwise handled)

Dev-mode behavior with `FastAPI(debug=True)`: requests error HTTP 409 with a message telling you to use the Vite dev server instead. Avoids accidentally using outdated `frontend-build` during development.

- `directory`: Path on local filesystem
- `index`: Index file name (default: `index.html`)
- `spa`: Serve index at any path (default: `False`)
- `catch_all`: Register a single catch-all handler instead of a route to each file; default for SPA
- `cached`: Path prefixes treated as immutable (default: `/assets/`)
- `favicon`: Optional path or glob (e.g. `/assets/logo*.png`)
- `zstdlevel`: Compression level (default: 18)

ℹ️ Even when your page has a meta tag giving favicon location, browsers still try loading `/favicon.ico` whenever looking at something else. We find it more convenient to simply serve the image where the browser expects it, with correct MIME type. This also allows having a default favicon for your application that can be easily overriden at the reverse proxy (Caddy, Nginx) to serve the company branding if needed in deployment.

## Server runner

When you need more flexibility than `fastapi` CLI can provide (e.g. CLI arguments to your own program), you may use this convenience to run FastAPI app with Uvicorn startup on given `listen` endpoints. Runs in the same process if possible but delegates to `uvicorn.run()` for auto-reloads and multiple workers. This would typically be called from your CLI main, which can set its own env variables to pass information to the FastAPI instances that run (Python imports only work in same-process mode).

```python
from fastapi_vue import server

server.run("my_app.app:app", listen=["localhost:8000"])
```

- As a deployment option, environment `FORWARDED_ALLOW_IPS` controls `X-Forwarded` trusted IPs (default: `127.0.0.1,::1`).
