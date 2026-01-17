"""Main FastAPI application."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi_vue import Frontend

# Frontend static file server - configure options here
frontend = Frontend(
    Path(__file__).parent / "frontend-build",
    spa=True,
    favicon="/assets/favicon",
    cached=["/assets/"],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage app startup and shutdown resources."""
    await frontend.load()
    yield


app = FastAPI(title="{{PROJECT_TITLE}}", lifespan=lifespan)


@app.get("/api/health")
async def health_check():
    """Health check endpoint for the dev server."""
    return {"status": "ok"}


# Add your API routes here
# @app.get("/api/example")
# async def example():
#     return {"message": "Hello World"}


frontend.route(app, "/")
