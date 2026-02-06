from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi_vue import Frontend
from MODULE_NAME.__main__ import DEVMODE

# Vue Frontend static files
frontend = Frontend(Path(__file__).with_name("frontend-build"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage app startup and shutdown resources."""
    await frontend.load()
    yield


app = FastAPI(title="PROJECT_TITLE", debug=DEVMODE, lifespan=lifespan)


# Add API routes here...


# Health check endpoint for the Vue demo app to verify the backend is running
@app.get("/api/health")
async def health_check():
    return {"status": "ok"}


# Serve the Vue frontend (needs to be last if SPA catch-all is used)
frontend.route(app, "/")
