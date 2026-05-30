"""
Account ORM model.

Represents a brokerage / financial account that owns one or more statements
and holds a portfolio of securities.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, List

from sqlalchemy import DateTime, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.holding import Holding
    from app.models.statement import Statement
    from app.models.activity import Activity


class Account(Base):
    """Brokerage account entity.

    Each account is uniquely identified by :attr:`account_number`.  Multiple
    PDF statements may be associated with a single account, and holdings are
    linked both to the account and the statement they were parsed from.
    """

    __tablename__ = "accounts"

    # ------------------------------------------------------------------
    # Primary key
    # ------------------------------------------------------------------
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
        doc="Surrogate UUID primary key.",
    )

    # ------------------------------------------------------------------
    # Business identity
    # ------------------------------------------------------------------
    account_number: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
        doc="Unique account identifier as printed on the statement.",
    )
    account_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Human-readable label for the account (e.g. 'Joint Taxable').",
    )
    broker_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Name of the brokerage or financial institution.",
    )

    # ------------------------------------------------------------------
    # Timestamps
    # ------------------------------------------------------------------
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        doc="UTC timestamp when this record was first inserted.",
    )

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------
    statements: Mapped[List["Statement"]] = relationship(
        "Statement",
        back_populates="account",
        cascade="all, delete-orphan",
        lazy="select",
        doc="All statements belonging to this account.",
    )
    holdings: Mapped[List["Holding"]] = relationship(
        "Holding",
        back_populates="account",
        cascade="all, delete-orphan",
        lazy="select",
        doc="All holdings ever recorded across all statements for this account.",
    )
    activities: Mapped[List["Activity"]] = relationship(
        "Activity",
        back_populates="account",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<Account id={self.id} account_number={self.account_number!r} "
            f"broker={self.broker_name!r}>"
        )
