"""
Pydantic schemas for Statement resources.

These schemas are used for request/response serialisation in the FastAPI
routers and are kept intentionally separate from the SQLAlchemy ORM models.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class StatementCreate(BaseModel):
    """Payload accepted when creating a statement record programmatically.

    In normal usage the upload endpoint constructs this from the multipart
    form data, but it is exposed here for testing and programmatic ingestion.
    """

    filename: str = Field(..., description="Server-side filename of the saved PDF.")
    original_filename: Optional[str] = Field(
        None, description="Original filename as supplied by the client."
    )
    account_id: Optional[uuid.UUID] = Field(
        None,
        description="Pre-existing account UUID to associate.  "
        "If omitted the ingestion pipeline resolves the account from parsed data.",
    )


class StatementResponse(BaseModel):
    """Full representation of a Statement returned to API clients."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: Optional[uuid.UUID] = None
    statement_date: Optional[date] = None
    filename: str
    original_filename: Optional[str] = None
    parse_status: str
    confidence_score: Optional[float] = None
    error_message: Optional[str] = None
    uploaded_at: datetime
    processed_at: Optional[datetime] = None

    # Denormalised account info (populated via join in the router)
    account_number: Optional[str] = Field(
        None, description="Account number from the related Account row."
    )
    broker_name: Optional[str] = Field(
        None, description="Broker name from the related Account row."
    )


class StatementListResponse(BaseModel):
    """Paginated list of statements."""

    items: List[StatementResponse] = Field(
        ..., description="Page of statement records."
    )
    total: int = Field(..., description="Total number of statements (unpaginated).")
    skip: int = Field(0, description="Number of records skipped (offset).")
    limit: int = Field(50, description="Maximum records returned per page.")
