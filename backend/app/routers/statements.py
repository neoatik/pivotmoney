"""
Statements router.

RESTful CRUD endpoints for brokerage statement PDFs.  The upload endpoint
saves the file to disk, creates a :class:`~app.models.statement.Statement`
record in ``pending`` state, and enqueues a background parsing task.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.database import get_db
from app.models.account import Account
from app.models.holding import Holding
from app.models.parse_log import ParseLog
from app.models.statement import Statement
from app.models.activity import Activity
from app.schemas.holding import HoldingListResponse, HoldingResponse
from app.schemas.statement import StatementListResponse, StatementResponse
from app.schemas.activity import ActivityResponse, ActivityListResponse
from app.tasks.background import process_statement_task

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/statements", tags=["statements"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _statement_to_response(stmt: Statement) -> StatementResponse:
    """Convert a :class:`Statement` ORM instance to a response schema."""
    account_number: Optional[str] = None
    broker_name: Optional[str] = None

    if stmt.account is not None:
        account_number = stmt.account.account_number
        broker_name = stmt.account.broker_name

    return StatementResponse(
        id=stmt.id,
        account_id=stmt.account_id,
        statement_date=stmt.statement_date,
        filename=stmt.filename,
        original_filename=stmt.original_filename,
        parse_status=stmt.parse_status,
        confidence_score=stmt.confidence_score,
        error_message=stmt.error_message,
        uploaded_at=stmt.uploaded_at,
        processed_at=stmt.processed_at,
        account_number=account_number,
        broker_name=broker_name,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/statements/upload
# ---------------------------------------------------------------------------

@router.post(
    "/upload",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a brokerage statement PDF",
)
async def upload_statement(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="PDF brokerage statement"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Accept a PDF upload, persist it to disk, and queue background parsing.

    Validations:
    * Content-type must be ``application/pdf``.
    * File size must not exceed :attr:`~app.config.Settings.max_file_size_mb`.

    Returns a JSON body with ``statement_id`` and ``status`` so the client
    can poll :meth:`get_statement` for updates.
    """
    settings = get_settings()

    # -- Content-type check ------------------------------------------------
    content_type = file.content_type or ""
    if "pdf" not in content_type.lower() and not (
        file.filename or ""
    ).lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF files are accepted.",
        )

    # -- Read file into memory for size check ------------------------------
    file_bytes = await file.read()
    if len(file_bytes) > settings.max_file_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"File exceeds the maximum allowed size of "
                f"{settings.max_file_size_mb} MB."
            ),
        )

    # -- Persist to disk ---------------------------------------------------
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    server_filename = f"{uuid.uuid4()}.pdf"
    file_path = upload_dir / server_filename

    with open(file_path, "wb") as fh:
        fh.write(file_bytes)

    logger.info(
        "Uploaded %s → %s (%d bytes)",
        file.filename,
        server_filename,
        len(file_bytes),
    )

    # -- Create statement record -------------------------------------------
    statement = Statement(
        filename=server_filename,
        original_filename=file.filename,
        parse_status="pending",
        uploaded_at=datetime.now(timezone.utc),
    )
    db.add(statement)
    await db.flush()
    statement_id = str(statement.id)

    # commit here so the background task can see the row
    await db.commit()

    # -- Enqueue background task -------------------------------------------
    background_tasks.add_task(
        process_statement_task,
        statement_id=statement_id,
        file_path=str(file_path.resolve()),
        db_url=settings.database_url,
    )

    return {
        "statement_id": statement_id,
        "status": "pending",
        "filename": server_filename,
        "original_filename": file.filename,
        "message": "File uploaded successfully.  Parsing has been queued.",
    }


# ---------------------------------------------------------------------------
# GET /api/v1/statements
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=StatementListResponse,
    summary="List all statements",
)
async def list_statements(
    account_id: Optional[uuid.UUID] = Query(None, description="Filter by account UUID."),
    skip: int = Query(0, ge=0, description="Number of records to skip."),
    limit: int = Query(50, ge=1, le=500, description="Maximum records to return."),
    db: AsyncSession = Depends(get_db),
) -> StatementListResponse:
    """Return a paginated list of all uploaded statements including account info."""
    count_query = select(func.count()).select_from(Statement)
    if account_id:
        count_query = count_query.where(Statement.account_id == account_id)
    count_result = await db.execute(count_query)
    total: int = count_result.scalar_one()

    query = (
        select(Statement)
        .options(selectinload(Statement.account))
        .order_by(Statement.uploaded_at.desc())
    )
    if account_id:
        query = query.where(Statement.account_id == account_id)

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    statements: List[Statement] = list(result.scalars().all())

    return StatementListResponse(
        items=[_statement_to_response(s) for s in statements],
        total=total,
        skip=skip,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/statements/{statement_id}
# ---------------------------------------------------------------------------

@router.get(
    "/{statement_id}",
    response_model=StatementResponse,
    summary="Get a single statement",
)
async def get_statement(
    statement_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> StatementResponse:
    """Return the full details of a single statement by its UUID."""
    result = await db.execute(
        select(Statement)
        .options(selectinload(Statement.account))
        .where(Statement.id == statement_id)
    )
    stmt: Optional[Statement] = result.scalar_one_or_none()
    if stmt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Statement {statement_id} not found.",
        )
    return _statement_to_response(stmt)


# ---------------------------------------------------------------------------
# GET /api/v1/statements/{statement_id}/holdings
# ---------------------------------------------------------------------------

@router.get(
    "/{statement_id}/holdings",
    response_model=HoldingListResponse,
    summary="Get holdings for a statement",
)
async def get_statement_holdings(
    statement_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> HoldingListResponse:
    """Return all holdings extracted from a specific statement."""
    # Verify statement exists
    stmt_exists = await db.execute(
        select(Statement.id).where(Statement.id == statement_id)
    )
    if stmt_exists.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Statement {statement_id} not found.",
        )

    count_result = await db.execute(
        select(func.count())
        .select_from(Holding)
        .where(Holding.statement_id == statement_id)
        .where(Holding.asset_type.not_like("allocation_%"))
    )
    total: int = count_result.scalar_one()

    result = await db.execute(
        select(Holding)
        .where(Holding.statement_id == statement_id)
        .where(Holding.asset_type.not_like("allocation_%"))
        .order_by(Holding.market_value.desc().nulls_last())
    )
    holdings: List[Holding] = list(result.scalars().all())

    return HoldingListResponse(
        items=[HoldingResponse.model_validate(h) for h in holdings],
        total=total,
        account_id=holdings[0].account_id if holdings else None,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/statements/{statement_id}/activities
# ---------------------------------------------------------------------------

@router.get(
    "/{statement_id}/activities",
    response_model=ActivityListResponse,
    summary="Get activities for a statement",
)
async def get_statement_activities(
    statement_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ActivityListResponse:
    """Return all transaction activities extracted from a specific statement."""
    # Verify statement exists
    stmt_exists = await db.execute(
        select(Statement.id).where(Statement.id == statement_id)
    )
    if stmt_exists.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Statement {statement_id} not found.",
        )

    count_result = await db.execute(
        select(func.count())
        .select_from(Activity)
        .where(Activity.statement_id == statement_id)
    )
    total: int = count_result.scalar_one()

    result = await db.execute(
        select(Activity)
        .where(Activity.statement_id == statement_id)
        .order_by(Activity.trade_date.desc().nulls_last(), Activity.created_at.desc())
    )
    activities: List[Activity] = list(result.scalars().all())

    return ActivityListResponse(
        items=[ActivityResponse.model_validate(a) for a in activities],
        total=total,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/statements/{statement_id}/logs
# ---------------------------------------------------------------------------

@router.get(
    "/{statement_id}/logs",
    summary="Get parse logs for a statement",
)
async def get_statement_logs(
    statement_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return all parse log entries for a statement, ordered by creation time."""
    stmt_exists = await db.execute(
        select(Statement.id).where(Statement.id == statement_id)
    )
    if stmt_exists.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Statement {statement_id} not found.",
        )

    result = await db.execute(
        select(ParseLog)
        .where(ParseLog.statement_id == statement_id)
        .order_by(ParseLog.created_at)
    )
    logs: List[ParseLog] = list(result.scalars().all())

    return {
        "statement_id": str(statement_id),
        "total": len(logs),
        "logs": [
            {
                "id": str(log.id),
                "level": log.level,
                "message": log.message,
                "field_name": log.field_name,
                "raw_value": log.raw_value,
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ],
    }


# ---------------------------------------------------------------------------
# DELETE /api/v1/statements/{statement_id}
# ---------------------------------------------------------------------------

@router.delete(
    "/{statement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a statement",
)
async def delete_statement(
    statement_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a statement and all its associated holdings and parse logs.

    The associated PDF file on disk is also removed if it exists.
    """
    result = await db.execute(
        select(Statement).where(Statement.id == statement_id)
    )
    stmt: Optional[Statement] = result.scalar_one_or_none()
    if stmt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Statement {statement_id} not found.",
        )

    # Remove file from disk
    settings = get_settings()
    file_path = Path(settings.upload_dir) / stmt.filename
    if file_path.exists():
        try:
            file_path.unlink()
            logger.info("Deleted file: %s", file_path)
        except OSError as exc:
            logger.warning("Could not delete file %s: %s", file_path, exc)

    await db.delete(stmt)
    # Holdings and ParseLogs cascade-delete via FK constraints
