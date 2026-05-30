"""
Holding ORM model.

Each Holding represents a single security / cash position extracted from a
brokerage statement.  Quantities and monetary values are stored with high
precision using PostgreSQL NUMERIC columns.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.account import Account
    from app.models.statement import Statement


class Holding(Base):
    """Individual security or cash position within a statement.

    Monetary columns use ``NUMERIC(18, N)`` to avoid floating-point rounding
    errors that are common with financial data.

    ``unrealized_gl`` and ``weight_pct`` are stored as parsed/computed values
    so that the database can be queried without re-deriving them at runtime.
    """

    __tablename__ = "holdings"

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
    # Foreign keys
    # ------------------------------------------------------------------
    statement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("statements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Statement from which this holding was extracted.",
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Owning account (denormalised from statement for query convenience).",
    )

    # ------------------------------------------------------------------
    # Security identity
    # ------------------------------------------------------------------
    asset_name: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        doc="Full name of the security as printed on the statement.",
    )
    ticker: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        index=True,
        doc="Exchange ticker symbol, uppercased and stripped of whitespace.",
    )
    asset_type: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        doc="Normalised asset class: stock | etf | bond | cash | mutual_fund | other",
    )

    # ------------------------------------------------------------------
    # Position details
    # ------------------------------------------------------------------
    quantity: Mapped[float | None] = mapped_column(
        Numeric(18, 6),
        nullable=True,
        doc="Number of shares / units held (up to 6 decimal places).",
    )
    market_value: Mapped[float | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
        doc="Current market value in :attr:`currency`.",
    )
    cost_basis: Mapped[float | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
        doc="Total cost basis (purchase price) of the position.",
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="USD",
        server_default="USD",
        doc="ISO 4217 currency code.  Defaults to USD.",
    )
    price_per_share: Mapped[float | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
        doc="Price per share / unit at the statement date.",
    )

    # ------------------------------------------------------------------
    # Computed / derived values
    # ------------------------------------------------------------------
    unrealized_gl: Mapped[float | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
        doc="Unrealised gain / loss = market_value - cost_basis.",
    )
    weight_pct: Mapped[float | None] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        doc="Percentage of total portfolio value this holding represents.",
    )

    # ------------------------------------------------------------------
    # Timestamps
    # ------------------------------------------------------------------
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------
    statement: Mapped["Statement"] = relationship(
        "Statement",
        back_populates="holdings",
        lazy="select",
    )
    account: Mapped["Account | None"] = relationship(
        "Account",
        back_populates="holdings",
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<Holding id={self.id} ticker={self.ticker!r} "
            f"asset_name={self.asset_name!r} market_value={self.market_value}>"
        )
