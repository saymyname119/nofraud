"""
app/main.py — FastAPI Application and Dependency Injection.

Spec §10.1:
  - 100% of I/O lives in the API route handler or its direct delegates.
  - The scoring and decision core remain pure functions.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import webhooks, dashboard
from app.database import init_db, get_session
from app.config import get_settings
from app.scoring.model import init_model

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting AegisPay API...")
    init_model("ml/artifact/model.pkl", "ml/artifact/version.json")
    await init_db()
    yield
    # Shutdown
    logger.info("Shutting down AegisPay API...")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AegisPay",
        version="1.0.0",
        lifespan=lifespan,
        debug=settings.app_env == "development"
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"], # Vite dev server
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(webhooks.router, prefix="/api/v1/webhooks", tags=["Webhooks"])
    app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["Dashboard"])
    return app

app = create_app()
