"""
Holdings Router
===============
Endpoints for querying holdings across all statements.
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.holding import Holding

router = APIRouter(prefix="/api/v1/holdings", tags=["holdings"])


@router.get("")
async def list_holdings(
    account_id: Optional[uuid.UUID] = Query(default=None, description="Filter by account UUID"),
    statement_id: Optional[uuid.UUID] = Query(default=None, description="Filter by statement UUID"),
    asset_type: Optional[str] = Query(default=None, description="Filter by asset type (stock/etf/bond/cash/mutual_fund/other)"),
    ticker: Optional[str] = Query(default=None, description="Filter by ticker symbol"),
    min_value: Optional[float] = Query(default=None, description="Minimum market value"),
    max_value: Optional[float] = Query(default=None, description="Maximum market value"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    sort_by: str = Query(default="market_value", description="Sort field: market_value|asset_name|ticker|unrealized_gl"),
    sort_dir: str = Query(default="desc", description="Sort direction: asc|desc"),
    db: AsyncSession = Depends(get_db),
):
    """
    List holdings with optional filters and sorting.

    Supports filtering by account, statement, asset type, ticker, and value range.
    """
    query = select(Holding).where(Holding.asset_type.not_like("allocation_%"))

    # Apply filters
    if account_id:
        query = query.where(Holding.account_id == account_id)
    if statement_id:
        query = query.where(Holding.statement_id == statement_id)
    if asset_type:
        query = query.where(Holding.asset_type == asset_type.lower())
    if ticker:
        query = query.where(Holding.ticker.ilike(f"%{ticker.upper()}%"))
    if min_value is not None:
        query = query.where(Holding.market_value >= min_value)
    if max_value is not None:
        query = query.where(Holding.market_value <= max_value)

    # Count total matching records
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Apply sorting
    sort_column = {
        "market_value": Holding.market_value,
        "asset_name": Holding.asset_name,
        "ticker": Holding.ticker,
        "unrealized_gl": Holding.unrealized_gl,
        "quantity": Holding.quantity,
        "weight_pct": Holding.weight_pct,
    }.get(sort_by, Holding.market_value)

    if sort_dir.lower() == "asc":
        query = query.order_by(sort_column.asc().nullslast())
    else:
        query = query.order_by(sort_column.desc().nullslast())

    query = query.offset(skip).limit(limit)

    result = await db.execute(query)
    holdings = result.scalars().all()

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "items": [_to_dict(h) for h in holdings],
    }


@router.get("/{holding_id}")
async def get_holding(
    holding_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a single holding by its UUID."""
    result = await db.execute(select(Holding).where(Holding.id == holding_id))
    holding = result.scalar_one_or_none()

    if not holding:
        raise HTTPException(status_code=404, detail="Holding not found")

    return _to_dict(holding)


def _to_dict(h: Holding) -> dict:
    return {
        "id": str(h.id),
        "statement_id": str(h.statement_id) if h.statement_id else None,
        "account_id": str(h.account_id) if h.account_id else None,
        "asset_name": h.asset_name,
        "ticker": h.ticker,
        "asset_type": h.asset_type,
        "quantity": float(h.quantity) if h.quantity is not None else None,
        "market_value": float(h.market_value) if h.market_value is not None else None,
        "cost_basis": float(h.cost_basis) if h.cost_basis is not None else None,
        "price_per_share": float(h.price_per_share) if h.price_per_share is not None else None,
        "currency": h.currency,
        "unrealized_gl": float(h.unrealized_gl) if h.unrealized_gl is not None else None,
        "weight_pct": float(h.weight_pct) if h.weight_pct is not None else None,
        "created_at": h.created_at.isoformat() if h.created_at else None,
    }
