"""FastAPI web application — subscription landing page & API."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.web.routes import router

logger = logging.getLogger("ai-news.web")

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    app = FastAPI(
        title="DeepFeed",
        description="AI News Aggregator — subscription & API layer",
        version="0.1.0",
    )

    # API routes
    app.include_router(router)

    # Serve static files (landing page, assets) at /static
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    return app
