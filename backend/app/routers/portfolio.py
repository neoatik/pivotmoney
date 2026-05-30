"""
Portfolio router.

Provides aggregated analytics endpoints that aggregate data across all
accounts and statements to give a holistic view of the portfolio.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.account import Account
from app.models.holding import Holding
from app.models.statement import Statement
from app.schemas.holding import HoldingResponse
from app.schemas.portfolio import AccountSummary, AssetAllocation, PortfolioSummary

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/portfolio", tags=["portfolio"])


# ---------------------------------------------------------------------------
# GET /api/v1/portfolio/summary
# ---------------------------------------------------------------------------

@router.get(
    "/summary",
    response_model=PortfolioSummary,
    summary="Aggregated portfolio summary",
)
async def get_portfolio_summary(
    account_id: Optional[uuid.UUID] = None,
    db: AsyncSession = Depends(get_db),
) -> PortfolioSummary:
    """Return a high-level summary of the entire portfolio.

    Aggregates market value, cost basis, unrealised G/L, holding counts,
    asset allocation, and the top 10 positions by value.
    """
    # -- Query special allocation rows first -------------------------------
    alloc_query = select(Holding).where(Holding.asset_type.like("allocation_%"))
    if account_id:
        alloc_query = alloc_query.where(Holding.account_id == account_id)
    alloc_h_result = await db.execute(alloc_query)
    alloc_holdings = alloc_h_result.scalars().all()

    # -- Standard totals (excluding allocation rows) -----------------------
    agg_query = select(
        func.coalesce(func.sum(Holding.market_value), 0).label("total_value"),
        func.coalesce(func.sum(Holding.cost_basis), 0).label("total_cost_basis"),
        func.count(Holding.id).label("num_holdings"),
    ).where(Holding.asset_type.not_like("allocation_%"))
    if account_id:
        agg_query = agg_query.where(Holding.account_id == account_id)
    agg_result = await db.execute(agg_query)
    agg = agg_result.one()

    num_holdings: int = int(agg.num_holdings)
    total_cost_basis: float = float(agg.total_cost_basis)

    # Use statement-level allocations sum if available to match PDF exactly
    if alloc_holdings:
        total_value = sum(float(h.market_value or 0) for h in alloc_holdings)
    else:
        total_value = float(agg.total_value)

    total_unrealized_gl: float = round(total_value - total_cost_basis, 2)
    total_unrealized_gl_pct: float = (
        round((total_unrealized_gl / total_cost_basis) * 100, 4)
        if total_cost_basis != 0
        else 0.0
    )

    # -- Account / statement counts ----------------------------------------
    if account_id:
        num_accounts = 1
    else:
        num_accounts_result = await db.execute(
            select(func.count(Account.id))
        )
        num_accounts = int(num_accounts_result.scalar_one())

    stmt_query = select(func.count(Statement.id))
    if account_id:
        stmt_query = stmt_query.where(Statement.account_id == account_id)
    num_statements_result = await db.execute(stmt_query)
    num_statements: int = int(num_statements_result.scalar_one())

    # -- Asset allocation --------------------------------------------------
    asset_allocation: List[AssetAllocation] = []
    if alloc_holdings:
        # Group by mapped type
        mapping = {
            "allocation_cash": "cash",
            "allocation_equities": "stock",
            "allocation_etfs": "etf",
            "allocation_other": "other",
        }
        alloc_map = {}
        for h in alloc_holdings:
            mapped_type = mapping.get(h.asset_type, "other")
            val = float(h.market_value or 0)
            if mapped_type not in alloc_map:
                alloc_map[mapped_type] = {"value": 0.0, "count": 0}
            alloc_map[mapped_type]["value"] += val
            
            # Count real positions in this asset type
            count_query = (
                select(func.count(Holding.id))
                .where((Holding.asset_type == mapped_type) & (Holding.asset_type.not_like("allocation_%")))
            )
            if account_id:
                count_query = count_query.where(Holding.account_id == account_id)
            count_res = await db.execute(count_query)
            alloc_map[mapped_type]["count"] = int(count_res.scalar_one() or 0)

        # Construct AssetAllocation objects
        for asset_type, info in alloc_map.items():
            row_value = info["value"]
            pct = round((row_value / total_value) * 100, 4) if total_value > 0 else 0.0
            asset_allocation.append(
                AssetAllocation(
                    asset_type=asset_type,
                    total_value=row_value,
                    pct=pct,
                    count=info["count"],
                )
            )
        asset_allocation.sort(key=lambda x: x.total_value, reverse=True)
    else:
        # Standard aggregation fallback
        alloc_query = (
            select(
                func.coalesce(Holding.asset_type, "other").label("asset_type"),
                func.coalesce(func.sum(Holding.market_value), 0).label("total_value"),
                func.count(Holding.id).label("count"),
            )
            .where(Holding.asset_type.not_like("allocation_%"))
            .group_by(Holding.asset_type)
        )
        if account_id:
            alloc_query = alloc_query.where(Holding.account_id == account_id)
        alloc_query = alloc_query.order_by(func.sum(Holding.market_value).desc().nulls_last())
        
        alloc_result = await db.execute(alloc_query)
        allocation_rows = alloc_result.all()
        for row in allocation_rows:
            row_value = float(row.total_value)
            pct = round((row_value / total_value) * 100, 4) if total_value > 0 else 0.0
            asset_allocation.append(
                AssetAllocation(
                    asset_type=row.asset_type,
                    total_value=row_value,
                    pct=pct,
                    count=int(row.count),
                )
            )

    # -- Top 10 holdings by market value -----------------------------------
    top_query = select(Holding).where(Holding.asset_type.not_like("allocation_%"))
    if account_id:
        top_query = top_query.where(Holding.account_id == account_id)
    top_query = top_query.order_by(Holding.market_value.desc().nulls_last()).limit(10)
    
    top_result = await db.execute(top_query)
    top_holdings_orm = list(top_result.scalars().all())
    top_holdings = [HoldingResponse.model_validate(h) for h in top_holdings_orm]

    return PortfolioSummary(
        total_value=total_value,
        total_cost_basis=total_cost_basis,
        total_unrealized_gl=total_unrealized_gl,
        total_unrealized_gl_pct=total_unrealized_gl_pct,
        num_holdings=num_holdings,
        num_accounts=num_accounts,
        num_statements=num_statements,
        currency="USD",
        asset_allocation=asset_allocation,
        top_holdings=top_holdings,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/portfolio/accounts
# ---------------------------------------------------------------------------

@router.get(
    "/accounts",
    response_model=List[AccountSummary],
    summary="Per-account portfolio summaries",
)
async def get_account_summaries(
    db: AsyncSession = Depends(get_db),
) -> List[AccountSummary]:
    """Return a summary for each account: total value, holding count, last statement date."""
    result = await db.execute(
        select(
            Account.id.label("account_id"),
            Account.account_number,
            Account.account_name,
            Account.broker_name,
            func.coalesce(func.sum(Holding.market_value), 0).label("total_value"),
            func.count(Holding.id).label("num_holdings"),
            func.max(Statement.statement_date).label("last_statement_date"),
        )
        .outerjoin(Holding, (Holding.account_id == Account.id) & (Holding.asset_type.not_like("allocation_%")))
        .outerjoin(Statement, Statement.account_id == Account.id)
        .group_by(Account.id, Account.account_number, Account.account_name, Account.broker_name)
        .order_by(func.sum(Holding.market_value).desc().nulls_last())
    )
    rows = result.all()

    summaries = []
    for row in rows:
        # Sum statement allocations for total value if present
        alloc_val_res = await db.execute(
            select(func.sum(Holding.market_value))
            .where((Holding.account_id == row.account_id) & (Holding.asset_type.like("allocation_%")))
        )
        alloc_val = alloc_val_res.scalar()
        
        total_val = float(alloc_val) if alloc_val is not None else float(row.total_value)
        summaries.append(
            AccountSummary(
                account_id=row.account_id,
                account_number=row.account_number,
                account_name=row.account_name,
                broker_name=row.broker_name,
                total_value=total_val,
                num_holdings=int(row.num_holdings),
                last_statement_date=row.last_statement_date,
            )
        )
    return summaries


# ---------------------------------------------------------------------------
# GET /api/v1/portfolio/allocation
# ---------------------------------------------------------------------------

@router.get(
    "/allocation",
    response_model=List[AssetAllocation],
    summary="Asset type allocation breakdown",
)
async def get_asset_allocation(
    account_id: Optional[uuid.UUID] = None,
    db: AsyncSession = Depends(get_db),
) -> List[AssetAllocation]:
    """Return the asset-type breakdown of the portfolio.

    The response is ordered by total value descending.  This endpoint is
    useful for rendering doughnut / pie charts on the frontend.
    """
    summary = await get_portfolio_summary(account_id=account_id, db=db)
    return summary.asset_allocation
