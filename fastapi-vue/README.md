# fastapi-vue

Implements Single-Page-App serving at site root with FastAPI, that the standard StaticFiles module cannot handle. This also caches and zstd compresses the files for lightning-fast operation. This is primarily meant for use with Vue frontend, but technically can host any static files in a similar manner.

## Installation

Script [fastapi-vue-setup](https://git.zi.fi/LeoVasanko/fastapi-vue-setup) should normally be used to convert or create a project with connection between FastAPI and Vue. The target project will depend on this package to serve its static files.

```sh
uvx fastapi-vue-setup --help
```

Refer to instructions below for further configuration.

## Usage

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi_vue import Frontend

frontend = Frontend(
    Path(__file__).with_name("frontend-build"),
    spa=True,
    cached=["/assets/"],
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await frontend.load()
    yield

app = FastAPI(lifespan=lifespan)

# Add API routes here...

# Final catch-all route for frontend files (keep at end of file)
frontend.route(app, "/")
```

## Configuration

- `directory`: Path to static files directory
- `spa`: Enable SPA mode (serve index.html for unknown routes)
- `cached`: Path prefixes for immutable cache headers (browser won't check for changes)
- `favicon`: Path to serve at `/favicon.ico` (e.g., `"/logo.png"` will be served as `image/png`)
- `zstdlevel`: Compression level (default: 18)
