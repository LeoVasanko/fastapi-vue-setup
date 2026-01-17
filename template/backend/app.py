from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi_vue import Frontend

# Vue Frontend static files
frontend = Frontend(
    Path(__file__).with_name("frontend-build"), spa=True, cached=["/assets/"]
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage app startup and shutdown resources."""
    await frontend.load()
    yield


app = FastAPI(title="PROJECT_TITLE", lifespan=lifespan)


# Add API routes here...


# Health check endpoint for the Vue demo app to verify the backend is running
@app.get("/api/health")
async def health_check():
    return {"status": "ok"}


# Final catch-all route for frontend files (keep at end of file)
frontend.route(app, "/")
