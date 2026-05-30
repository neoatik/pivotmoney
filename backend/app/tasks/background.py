"""
Background Task — Async PDF Processing Pipeline
================================================
Runs the full parse → normalize → store pipeline in the background,
outside of the request/response cycle. Creates its own DB session.
"""

from __future__ import annotations

import logging
import traceback
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.services.pdf_parser import parse_pdf
from app.services.ingestion import (
    get_or_create_account,
    save_holdings,
    save_parse_logs,
    update_statement_status,
    save_activities,
)

logger = logging.getLogger(__name__)


async def process_statement_task(
    statement_id: str,
    file_path: str,
    db_url: str,
) -> None:
    """
    Background task that processes a PDF statement end-to-end.

    This function creates its own database engine and session because
    it runs outside the request lifecycle (FastAPI BackgroundTasks).

    Pipeline:
        1. Update statement status → 'processing'
        2. Parse PDF (AI + regex multi-strategy)
        3. Get or create Account record
        4. Save holdings to DB
        5. Save parse logs
        6. Update statement with final status, confidence, metadata

    Args:
        statement_id: UUID string of the Statement record to process.
        file_path: Absolute path to the uploaded PDF file.
        db_url: Full database URL for creating a fresh async engine.
    """
    stmt_uuid = uuid.UUID(statement_id)
    logger.info("Starting background processing for statement %s", statement_id)

    # Create a fresh engine + session for the background task
    engine = create_async_engine(db_url, echo=False, pool_pre_ping=True)
    AsyncSessionFactory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with AsyncSessionFactory() as db:
        async with db.begin():
            # ── Step 1: Mark as processing ─────────────────────────────────
            await update_statement_status(db, stmt_uuid, status="processing")

    async with AsyncSessionFactory() as db:
        async with db.begin():
            try:
                # ── Step 2: Parse the PDF ──────────────────────────────────
                logger.info("Parsing PDF: %s", file_path)
                parse_result = await parse_pdf(file_path)

                # ── Step 3: Determine account ──────────────────────────────
                # Use parsed account number, or generate a placeholder
                account_number = parse_result.account_number or f"UNKNOWN-{stmt_uuid.hex[:8].upper()}"
                account = await get_or_create_account(
                    db,
                    account_number=account_number,
                    account_name=parse_result.account_name,
                    broker_name=parse_result.broker_name,
                )

                # ── Step 4: Link statement to account & save metadata ──────
                from sqlalchemy import select
                from app.models.statement import Statement

                result = await db.execute(
                    select(Statement).where(Statement.id == stmt_uuid)
                )
                statement = result.scalar_one_or_none()

                if statement:
                    statement.account_id = account.id
                    statement.statement_date = parse_result.statement_date
                    statement.raw_text = parse_result.raw_text[:50000] if parse_result.raw_text else ""

                # ── Step 5: Calculate total portfolio value ────────────────
                total_value = sum(
                    float(h.market_value or 0)
                    for h in parse_result.holdings
                    if h.market_value is not None
                )

                # ── Step 6: Save holdings ──────────────────────────────────
                holdings_count = await save_holdings(
                    db,
                    statement_id=stmt_uuid,
                    account_id=account.id,
                    holdings_data=parse_result.holdings,
                    total_portfolio_value=total_value,
                )

                # ── Step 7: Save parse logs ────────────────────────────────
                await save_parse_logs(db, stmt_uuid, parse_result.logs)

                # ── Step 7.5: Save transaction activities ──────────────────
                await save_activities(
                    db,
                    statement_id=stmt_uuid,
                    account_id=account.id,
                    activities_data=parse_result.activities,
                )

                # ── Step 8: Final status update ────────────────────────────
                if holdings_count > 0 and parse_result.confidence_score >= 0.5:
                    final_status = "success"
                elif holdings_count > 0:
                    final_status = "partial"
                else:
                    final_status = "failed"

                await update_statement_status(
                    db,
                    stmt_uuid,
                    status=final_status,
                    confidence=parse_result.confidence_score,
                    processed_at=datetime.now(timezone.utc),
                )

                logger.info(
                    "Statement %s processed: status=%s, holdings=%d, confidence=%.2f",
                    statement_id,
                    final_status,
                    holdings_count,
                    parse_result.confidence_score,
                )

            except Exception as exc:
                # ── Error handling ─────────────────────────────────────────
                error_msg = f"{type(exc).__name__}: {str(exc)}"
                logger.error(
                    "Background processing failed for statement %s: %s\n%s",
                    statement_id,
                    error_msg,
                    traceback.format_exc(),
                )
                await update_statement_status(
                    db,
                    stmt_uuid,
                    status="failed",
                    confidence=0.0,
                    error_message=error_msg[:1000],
                    processed_at=datetime.now(timezone.utc),
                )

    await engine.dispose()
    logger.info("Background task complete for statement %s", statement_id)
