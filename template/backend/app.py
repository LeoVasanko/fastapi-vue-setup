"""FastAPI application module with Vue frontend integration."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import fastapi_vue
from fastapi import FastAPI

# Vue Frontend static files
frontend = fastapi_vue.Frontend(Path(__file__).with_name("frontend-build"))


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator:
    """Manage app startup and shutdown resources."""
    await frontend.load()
    yield


app = FastAPI(title="PROJECT_TITLE", debug=fastapi_vue.env.dev, lifespan=lifespan)


# Add API routes here...


# Health check endpoint for the Vue demo app to verify the backend is running
@app.get("/api/health")
async def health_check() -> dict:
    """Return backend status for health monitoring."""
    return {"status": "ok"}


# Serve the Vue frontend (needs to be last if SPA catch-all is used)
frontend.route(app, "/")
