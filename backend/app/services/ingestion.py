"""
Database Ingestion Service
===========================
Functions for writing parsed financial data to the PostgreSQL database.
All functions are async and use SQLAlchemy's async session.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.holding import Holding
from app.models.parse_log import ParseLog
from app.models.statement import Statement
from app.services.normalizer import compute_unrealized_gl, compute_weight

logger = logging.getLogger(__name__)


async def get_or_create_account(
    db: AsyncSession,
    account_number: str,
    account_name: Optional[str] = None,
    broker_name: Optional[str] = None,
) -> Account:
    """
    Retrieve an existing account by number, or create one if it doesn't exist.

    Uses a SELECT-then-INSERT pattern to handle concurrent uploads safely.

    Args:
        db: Active async SQLAlchemy session.
        account_number: The brokerage account number (unique identifier).
        account_name: Optional display name for the account holder.
        broker_name: Optional name of the brokerage firm.

    Returns:
        The Account ORM object (existing or newly created).
    """
    # Normalize account number
    account_number = account_number.strip().upper()

    # Try to find existing account
    result = await db.execute(
        select(Account).where(Account.account_number == account_number)
    )
    existing = result.scalar_one_or_none()

    if existing:
        # Update metadata if we have better info now
        updated = False
        if account_name and not existing.account_name:
            existing.account_name = account_name
            updated = True
        if broker_name and not existing.broker_name:
            existing.broker_name = broker_name
            updated = True
        if updated:
            await db.flush()
        logger.info("Found existing account: %s", account_number)
        return existing

    # Create new account
    account = Account(
        id=uuid.uuid4(),
        account_number=account_number,
        account_name=account_name,
        broker_name=broker_name,
    )
    db.add(account)
    await db.flush()  # Get the ID without committing
    logger.info("Created new account: %s (id=%s)", account_number, account.id)
    return account


async def save_statement(
    db: AsyncSession,
    account_id: uuid.UUID,
    filename: str,
    original_filename: str,
    raw_text: str = "",
) -> Statement:
    """
    Create a new Statement record in the database.

    Args:
        db: Active async SQLAlchemy session.
        account_id: UUID of the parent account.
        filename: Stored filename on disk (UUID-based).
        original_filename: Original filename from the upload.
        raw_text: Full extracted text from the PDF (for audit/reprocessing).

    Returns:
        The newly created Statement ORM object.
    """
    statement = Statement(
        id=uuid.uuid4(),
        account_id=account_id,
        filename=filename,
        original_filename=original_filename,
        raw_text=raw_text,
        parse_status="pending",
        uploaded_at=datetime.now(timezone.utc),
    )
    db.add(statement)
    await db.flush()
    logger.info("Created statement record: %s", statement.id)
    return statement


async def update_statement_status(
    db: AsyncSession,
    statement_id: uuid.UUID,
    status: str,
    confidence: Optional[float] = None,
    error_message: Optional[str] = None,
    processed_at: Optional[datetime] = None,
) -> None:
    """
    Update the parse status and metadata of a Statement.

    Args:
        db: Active async SQLAlchemy session.
        statement_id: UUID of the statement to update.
        status: New parse status ('pending'|'processing'|'success'|'partial'|'failed').
        confidence: Parsing confidence score (0.0–1.0).
        error_message: Error message if status is 'failed'.
        processed_at: Timestamp when processing completed.
    """
    result = await db.execute(select(Statement).where(Statement.id == statement_id))
    statement = result.scalar_one_or_none()

    if not statement:
        logger.error("Statement not found for status update: %s", statement_id)
        return

    statement.parse_status = status
    if confidence is not None:
        statement.confidence_score = round(confidence, 4)
    if error_message is not None:
        statement.error_message = error_message
    if processed_at is not None:
        statement.processed_at = processed_at

    await db.flush()
    logger.info("Updated statement %s status → %s", statement_id, status)


async def save_holdings(
    db: AsyncSession,
    statement_id: uuid.UUID,
    account_id: uuid.UUID,
    holdings_data: list[Any],  # list of ParsedHolding objects or dicts
    total_portfolio_value: float = 0.0,
) -> int:
    """
    Bulk-insert holdings for a statement into the database.

    Deletes any existing holdings for the statement first (idempotent re-processing).

    Args:
        db: Active async SQLAlchemy session.
        statement_id: UUID of the parent statement.
        account_id: UUID of the parent account.
        holdings_data: List of ParsedHolding objects or dicts.
        total_portfolio_value: Total portfolio value (for weight calculation).

    Returns:
        Number of holdings successfully saved.
    """
    # Delete existing holdings (for idempotent reprocessing)
    existing = await db.execute(
        select(Holding).where(Holding.statement_id == statement_id)
    )
    for h in existing.scalars().all():
        await db.delete(h)

    saved_count = 0
    for item in holdings_data:
        # Support both dataclass and dict inputs
        if hasattr(item, "__dataclass_fields__"):
            # ParsedHolding dataclass
            name = item.asset_name
            ticker = item.ticker
            asset_type = item.asset_type
            qty = item.quantity
            mv = item.market_value
            cb = item.cost_basis
            price = item.price_per_share
            currency = item.currency or "USD"
            unrealized_gl = item.unrealized_gl
            weight_pct = item.weight_pct
        else:
            # Plain dict
            name = item.get("asset_name") or item.get("name") or ""
            ticker = item.get("ticker")
            asset_type = item.get("asset_type")
            qty = item.get("quantity")
            mv = item.get("market_value")
            cb = item.get("cost_basis")
            price = item.get("price_per_share")
            currency = item.get("currency", "USD")
            unrealized_gl = compute_unrealized_gl(mv, cb)
            weight_pct = compute_weight(mv, total_portfolio_value)

        if not name:
            continue

        holding = Holding(
            id=uuid.uuid4(),
            statement_id=statement_id,
            account_id=account_id,
            asset_name=name,
            ticker=ticker,
            asset_type=asset_type or "other",
            quantity=qty,
            market_value=mv,
            cost_basis=cb,
            price_per_share=price,
            currency=currency,
            unrealized_gl=unrealized_gl,
            weight_pct=weight_pct,
        )
        db.add(holding)
        saved_count += 1

    await db.flush()
    logger.info("Saved %d holdings for statement %s", saved_count, statement_id)
    return saved_count


async def save_parse_logs(
    db: AsyncSession,
    statement_id: uuid.UUID,
    logs: list[Any],  # list of ParseLogEntry objects or dicts
) -> None:
    """
    Save parse audit log entries for a statement.

    Args:
        db: Active async SQLAlchemy session.
        statement_id: UUID of the parent statement.
        logs: List of log entries (ParseLogEntry dataclass or dicts with level/message).
    """
    for item in logs:
        if hasattr(item, "__dataclass_fields__"):
            level = item.level
            message = item.message
            field_name = item.field_name
            raw_value = item.raw_value
        else:
            level = item.get("level", "info")
            message = item.get("message", "")
            field_name = item.get("field_name")
            raw_value = item.get("raw_value")

        log_entry = ParseLog(
            id=uuid.uuid4(),
            statement_id=statement_id,
            level=level,
            message=message,
            field_name=field_name,
            raw_value=str(raw_value)[:500] if raw_value else None,  # Truncate long values
        )
        db.add(log_entry)

    await db.flush()
    logger.info("Saved %d parse log entries for statement %s", len(logs), statement_id)


async def save_activities(
    db: AsyncSession,
    statement_id: uuid.UUID,
    account_id: uuid.UUID,
    activities_data: list[dict[str, Any]],
) -> int:
    """
    Bulk-insert activities (transactions) for a statement into the database.
    Deletes any existing activities for the statement first (idempotent re-processing).

    Args:
        db: Active async SQLAlchemy session.
        statement_id: UUID of the parent statement.
        account_id: UUID of the parent account.
        activities_data: List of activity dicts.

    Returns:
        Number of activities successfully saved.
    """
    from app.models.activity import Activity
    from sqlalchemy import delete
    from app.services.normalizer import normalize_amount, normalize_date

    # Delete existing activities
    await db.execute(
        delete(Activity).where(Activity.statement_id == statement_id)
    )

    saved_count = 0
    for item in activities_data:
        date_raw = item.get("trade_date") or item.get("date")
        trade_date = normalize_date(str(date_raw)) if date_raw else None
        
        act_type = str(item.get("activity_type") or item.get("activity") or "OTHER").strip().upper()
        desc = str(item.get("description") or "Transaction").strip()
        
        qty = item.get("quantity") or item.get("qty")
        if qty is not None and str(qty).strip() not in ("", "-"):
            try:
                qty_val = float(str(qty).replace(",", "").strip())
            except ValueError:
                qty_val = None
        else:
            qty_val = None
            
        rate = item.get("price") or item.get("rate")
        rate_val = normalize_amount(str(rate)) if rate is not None and str(rate).strip() not in ("", "-") else None
        
        amt = item.get("amount")
        amt_val = normalize_amount(str(amt)) if amt is not None else None
        
        currency = item.get("currency") or "USD"

        activity = Activity(
            id=uuid.uuid4(),
            statement_id=statement_id,
            account_id=account_id,
            trade_date=trade_date,
            activity_type=act_type,
            description=desc,
            quantity=qty_val,
            price=rate_val,
            amount=amt_val,
            currency=currency,
        )
        db.add(activity)
        saved_count += 1

    await db.flush()
    logger.info("Saved %d transaction activities for statement %s", saved_count, statement_id)
    return saved_count

