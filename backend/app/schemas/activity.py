"""
Pydantic schemas for Activity (transaction) resources.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ActivityResponse(BaseModel):
    """Full representation of a transaction activity returned to API clients."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    statement_id: uuid.UUID
    account_id: Optional[uuid.UUID] = None
    trade_date: Optional[date] = None
    activity_type: str = Field(..., description="BUY | SELL | DIVIDEND | DEPOSIT | WITHDRAWAL | etc.")
    description: str
    quantity: Optional[float] = None
    price: Optional[float] = Field(None, alias="price")  # Alias or name as price/rate
    amount: Optional[float] = None
    currency: str = "USD"
    created_at: datetime


class ActivityListResponse(BaseModel):
    """Paginated list of activity entries."""

    items: List[ActivityResponse] = Field(..., description="Page of activity records.")
    total: int = Field(..., description="Total number of activities.")
