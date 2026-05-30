"""
Pydantic schemas for Holding resources.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class HoldingResponse(BaseModel):
    """Full representation of a single Holding position."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    statement_id: uuid.UUID
    account_id: Optional[uuid.UUID] = None

    asset_name: str
    ticker: Optional[str] = None
    asset_type: Optional[str] = None

    quantity: Optional[float] = None
    market_value: Optional[float] = None
    cost_basis: Optional[float] = None
    currency: str = "USD"
    price_per_share: Optional[float] = None
    unrealized_gl: Optional[float] = None
    weight_pct: Optional[float] = None

    created_at: datetime


class HoldingListResponse(BaseModel):
    """Paginated list of holdings, optionally scoped to a single account."""

    items: List[HoldingResponse] = Field(..., description="Page of holding records.")
    total: int = Field(..., description="Total number of matching holdings.")
    account_id: Optional[uuid.UUID] = Field(
        None, description="Account filter applied, if any."
    )
    skip: int = Field(0)
    limit: int = Field(50)
