from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    """Timezone-aware current time in UTC."""
    return datetime.now(timezone.utc)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Idempotency — layered. A duplicate is rejected if it matches on EITHER.
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64))

    # The message itself.
    sender: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str | None] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    jobs: Mapped[list["Job"]] = relationship(back_populates="message")

    __table_args__ = (
        UniqueConstraint("provider_message_id", name="uq_messages_provider_id"),
        UniqueConstraint("content_hash", name="uq_messages_content_hash"),
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)

    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id"), index=True
    )

    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    message: Mapped["Message"] = relationship(back_populates="jobs")

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'done', 'failed', 'dead')",
            name="ck_jobs_status_valid",
        ),
    )