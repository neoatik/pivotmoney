"""
Health-check router.

Provides lightweight endpoints that confirm the API process is running and
that the database connection is healthy.  Typically consumed by load
balancers, orchestrators (Kubernetes liveness / readiness probes), and
monitoring systems.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db

router = APIRouter(tags=["health"])


async def _check_db(db: AsyncSession) -> str:
    """Return ``'ok'`` if the database responds to a simple query, else ``'error'``."""
    try:
        await db.execute(text("SELECT 1"))
        return "ok"
    except Exception:  # pylint: disable=broad-except
        return "error"


@router.get("/health", summary="Basic health check")
async def health_check(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Return the health status of the API and its database connection.

    Response body::

        {
          "status": "ok",
          "db": "ok",
          "version": "1.0.0"
        }

    The ``db`` field will be ``"error"`` when the database is unreachable.
    """
    db_status = await _check_db(db)
    return {
        "status": "ok",
        "db": db_status,
        "version": "1.0.0",
    }


@router.get("/api/v1/health", summary="Versioned health check")
async def health_check_v1(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Versioned alias of :func:`health_check` mounted under ``/api/v1``."""
    db_status = await _check_db(db)
    return {
        "status": "ok",
        "db": db_status,
        "version": "1.0.0",
    }
