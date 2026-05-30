"""
ParseLog ORM model.

Stores structured log entries emitted during the PDF parsing pipeline.
Each entry is associated with a Statement and carries a severity level,
a human-readable message, and optional field-level metadata to aid
debugging of extraction failures.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.statement import Statement


class ParseLog(Base):
    """A single log entry emitted by the parsing pipeline.

    Severity levels mirror Python's logging levels in spirit:

    * **info**    – a noteworthy decision or successful extraction step
    * **warning** – a non-fatal issue (e.g. ambiguous value that was guessed)
    * **error**   – a field could not be extracted or a value failed validation
    """

    __tablename__ = "parse_logs"

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
    statement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("statements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="The statement this log entry belongs to.",
    )

    # ------------------------------------------------------------------
    # Log payload
    # ------------------------------------------------------------------
    level: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        doc="Severity level: info | warning | error",
    )
    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Human-readable description of the parsing event.",
    )
    field_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        doc="Name of the model field being extracted when the event occurred.",
    )
    raw_value: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="The raw string value from the PDF that triggered this log entry.",
    )

    # ------------------------------------------------------------------
    # Timestamp
    # ------------------------------------------------------------------
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        doc="UTC timestamp when this log entry was created.",
    )

    # ------------------------------------------------------------------
    # Relationship
    # ------------------------------------------------------------------
    statement: Mapped["Statement"] = relationship(
        "Statement",
        back_populates="parse_logs",
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<ParseLog id={self.id} level={self.level!r} "
            f"field={self.field_name!r} message={self.message[:60]!r}>"
        )
