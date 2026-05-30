"""
Statement ORM model.

A Statement tracks the lifecycle of a single PDF upload — from initial
upload through parsing to successful data extraction.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, List

from sqlalchemy import Date, DateTime, Float, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.account import Account
    from app.models.holding import Holding
    from app.models.parse_log import ParseLog
    from app.models.activity import Activity


class Statement(Base):
    """Represents one uploaded brokerage statement PDF.

    The parsing pipeline moves a statement through the following states:

    ``pending`` → ``processing`` → ``success`` | ``partial`` | ``failed``

    *  **pending**    – file saved, background task not yet started
    *  **processing** – background task is actively parsing
    *  **success**    – all holdings extracted with high confidence
    *  **partial**    – some holdings extracted but confidence is low
    *  **failed**     – parsing failed completely
    """

    __tablename__ = "statements"

    # ------------------------------------------------------------------
    # Primary key
    # ------------------------------------------------------------------
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )

    # ------------------------------------------------------------------
    # Foreign key
    # ------------------------------------------------------------------
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Account this statement belongs to (resolved during parsing).",
    )

    # ------------------------------------------------------------------
    # Statement metadata
    # ------------------------------------------------------------------
    statement_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        doc="The period-ending date printed on the statement.",
    )
    filename: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        doc="Server-side filename (UUID-prefixed) used to locate the file on disk.",
    )
    original_filename: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        doc="Original filename as provided by the uploader.",
    )

    # ------------------------------------------------------------------
    # Extracted content
    # ------------------------------------------------------------------
    raw_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Full text extracted from the PDF (used for AI parsing).",
    )

    # ------------------------------------------------------------------
    # Parse status
    # ------------------------------------------------------------------
    parse_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        server_default="pending",
        doc="Current parse status: pending | processing | success | partial | failed",
    )
    confidence_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        doc="Overall parser confidence in [0, 1].  Set after parsing completes.",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Human-readable error description when parse_status is 'failed'.",
    )

    # ------------------------------------------------------------------
    # Timestamps
    # ------------------------------------------------------------------
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        doc="UTC timestamp when the file was uploaded.",
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="UTC timestamp when parsing finished (success or failure).",
    )

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------
    account: Mapped["Account | None"] = relationship(
        "Account",
        back_populates="statements",
        lazy="select",
    )
    holdings: Mapped[List["Holding"]] = relationship(
        "Holding",
        back_populates="statement",
        cascade="all, delete-orphan",
        lazy="select",
    )
    activities: Mapped[List["Activity"]] = relationship(
        "Activity",
        back_populates="statement",
        cascade="all, delete-orphan",
        lazy="select",
    )
    parse_logs: Mapped[List["ParseLog"]] = relationship(
        "ParseLog",
        back_populates="statement",
        cascade="all, delete-orphan",
        lazy="select",
        order_by="ParseLog.created_at",
    )

    def __repr__(self) -> str:
        return (
            f"<Statement id={self.id} filename={self.filename!r} "
            f"status={self.parse_status!r}>"
        )
