"""
FastAPI application entry point.

This module creates and configures the FastAPI application instance,
registers all middleware and routers, sets up static file serving, and
defines startup / shutdown lifecycle hooks.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import init_db
from app.routers import health, holdings, portfolio, statements, activities

logger = logging.getLogger(__name__)

settings = get_settings()

# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title=settings.app_name,
    description=(
        "Financial Data Ingestion Engine that parses brokerage PDF statements "
        "using a multi-strategy pipeline (AI + regex) and exposes the extracted "
        "portfolio data via a RESTful API."
    ),
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# ---------------------------------------------------------------------------
# CORS — allow all origins in development
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(health.router)
app.include_router(statements.router)
app.include_router(holdings.router)
app.include_router(portfolio.router)
app.include_router(activities.router)

# ---------------------------------------------------------------------------
# Static file mounts
# ---------------------------------------------------------------------------

# Serve uploaded PDFs at /uploads/<filename>
_upload_dir = Path(settings.upload_dir)
_upload_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(_upload_dir)), name="uploads")

# Serve the frontend SPA. We check two locations: the parent's parent's parent (local dev)
# and parent's parent (Docker container mounting /app/frontend).
_frontend_dir = Path(__file__).parent.parent.parent / "frontend"
if not _frontend_dir.exists():
    _frontend_dir = Path(__file__).parent.parent / "frontend"

if _frontend_dir.exists():
    app.mount(
        "/",
        StaticFiles(directory=str(_frontend_dir), html=True),
        name="frontend",
    )
else:
    logger.warning(
        "Frontend directory not found at %s — skipping static mount.",
        _frontend_dir,
    )


# ---------------------------------------------------------------------------
# Lifecycle events
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def on_startup() -> None:
    """Run once when the application starts.

    Creates the upload directory and initialises the database tables (using
    SQLAlchemy ``create_all`` — safe to run against an existing schema).
    """
    upload_path = Path(settings.upload_dir)
    upload_path.mkdir(parents=True, exist_ok=True)
    logger.info("Upload directory ready: %s", upload_path.resolve())

    await init_db()
    logger.info("Database tables initialised.")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    """Graceful shutdown hook."""
    logger.info("PivotMoney backend shutting down.")


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return a structured 422 response for Pydantic / FastAPI validation errors."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": exc.errors(),
            "body": str(exc.body)[:500] if hasattr(exc, "body") else None,
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Return a 500 response for any unhandled exception.

    In production the error message should not expose internal details;
    here we include it only when ``debug=True``.
    """
    logger.exception("Unhandled exception for %s %s", request.method, request.url)
    detail = str(exc) if settings.debug else "An internal server error occurred."
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": detail},
    )
