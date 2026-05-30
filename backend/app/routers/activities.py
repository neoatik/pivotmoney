"""
Activities router.

Provides endpoints to query transaction activities parsed from statement PDFs.
"""

from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.activity import Activity
from app.schemas.activity import ActivityListResponse, ActivityResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/activities", tags=["activities"])


@router.get(
    "",
    response_model=ActivityListResponse,
    summary="List all transaction activities",
)
async def list_activities(
    statement_id: Optional[uuid.UUID] = Query(None, description="Filter by statement UUID."),
    account_id: Optional[uuid.UUID] = Query(None, description="Filter by account UUID."),
    skip: int = Query(0, ge=0, description="Offset for pagination."),
    limit: int = Query(50, ge=1, le=500, description="Limit for pagination."),
    db: AsyncSession = Depends(get_db),
) -> ActivityListResponse:
    """Return a list of all transaction activities matching the filters."""
    query = select(Activity)

    if statement_id:
        query = query.where(Activity.statement_id == statement_id)
    if account_id:
        query = query.where(Activity.account_id == account_id)

    # Count total matching records
    count_query = select(func.count()).select_from(query.subquery())
    count_result = await db.execute(count_query)
    total = count_result.scalar_one()

    # Get page of records
    query = query.order_by(Activity.trade_date.desc().nulls_last(), Activity.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    activities = result.scalars().all()

    return ActivityListResponse(
        items=[ActivityResponse.model_validate(a) for a in activities],
        total=total,
    )
