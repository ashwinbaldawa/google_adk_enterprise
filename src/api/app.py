"""FastAPI app — serves evaluation dashboard UI + API endpoints."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .routes import router


def create_app() -> FastAPI:
    app = FastAPI(
        title="ADK Enterprise Dashboard",
        description="Evaluation metrics & usage analytics for ADK Agent Platform",
        version="1.0.0",
    )

    # API routes
    app.include_router(router)

    # Serve dashboard HTML
    dashboard_dir = Path(__file__).parent.parent.parent / "dashboard"

    @app.get("/")
    async def serve_dashboard():
        return FileResponse(dashboard_dir / "index.html")

    return app
