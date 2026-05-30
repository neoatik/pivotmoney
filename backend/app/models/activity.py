"""
Activity ORM model.

Each Activity represents a single transaction (trade, dividend, deposit, withdrawal)
extracted from a brokerage statement.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.account import Account
    from app.models.statement import Statement


class Activity(Base):
    """Transaction activity records from a statement.
    
    Includes trades (BUY/SELL), income (DIVIDEND/INTEREST), and funding (DEPOSIT/WITHDRAWAL).
    """

    __tablename__ = "activities"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )

    # Foreign keys
    statement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("statements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Statement this activity was extracted from.",
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Related account.",
    )

    # Activity details
    trade_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        doc="Trade or transaction date.",
    )
    activity_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        doc="Type of transaction (BUY | SELL | DIVIDEND | DEPOSIT | WITHDRAWAL | INTEREST | OTHER).",
    )
    description: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
        doc="Text description of the transaction.",
    )
    quantity: Mapped[float | None] = mapped_column(
        Numeric(18, 6),
        nullable=True,
        doc="Quantity of shares (for trades).",
    )
    price: Mapped[float | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
        doc="Price/rate per unit (for trades).",
    )
    amount: Mapped[float | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
        doc="Net dollar amount of the transaction.",
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="USD",
        server_default="USD",
        doc="ISO currency code.",
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    # Relationships
    statement: Mapped["Statement"] = relationship(
        "Statement",
        back_populates="activities",
        lazy="select",
    )
    account: Mapped["Account | None"] = relationship(
        "Account",
        back_populates="activities",
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<Activity id={self.id} date={self.trade_date} "
            f"type={self.activity_type!r} amount={self.amount}>"
        )
