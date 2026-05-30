"""
Pydantic schemas for portfolio-level aggregation endpoints.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.holding import HoldingResponse


class AssetAllocation(BaseModel):
    """Breakdown of portfolio value by asset type."""

    asset_type: str = Field(
        ..., description="Normalised asset class (stock / etf / bond / cash / …)."
    )
    total_value: float = Field(
        ..., description="Sum of market values for this asset class."
    )
    pct: float = Field(
        ..., description="Percentage of total portfolio value (0–100)."
    )
    count: int = Field(..., description="Number of holdings in this asset class.")


class PortfolioSummary(BaseModel):
    """Aggregated summary across all accounts and statements."""

    total_value: float = Field(..., description="Sum of all holding market values.")
    total_cost_basis: float = Field(
        ..., description="Sum of all holding cost bases."
    )
    total_unrealized_gl: float = Field(
        ..., description="Total unrealised gain / loss (total_value - total_cost_basis)."
    )
    total_unrealized_gl_pct: float = Field(
        ...,
        description="Unrealised G/L as a percentage of total cost basis.  "
        "Returns 0 when cost basis is zero.",
    )
    num_holdings: int = Field(..., description="Total number of holding rows.")
    num_accounts: int = Field(..., description="Number of distinct accounts.")
    num_statements: int = Field(..., description="Number of uploaded statements.")
    currency: str = Field("USD", description="Primary display currency.")
    asset_allocation: List[AssetAllocation] = Field(
        ..., description="Per-asset-class breakdown."
    )
    top_holdings: List[HoldingResponse] = Field(
        ..., description="Top 10 holdings by market value."
    )


class AccountSummary(BaseModel):
    """Per-account portfolio snapshot."""

    account_id: uuid.UUID
    account_number: str
    account_name: Optional[str] = None
    broker_name: Optional[str] = None
    total_value: float = Field(..., description="Sum of market values in this account.")
    num_holdings: int = Field(..., description="Number of holdings in this account.")
    last_statement_date: Optional[date] = Field(
        None, description="Most recent statement date for this account."
    )
