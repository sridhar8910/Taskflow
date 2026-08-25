import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class NotificationType(str, enum.Enum):
    overdue = "overdue"
    reassigned = "reassigned"


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint(
            "task_id", "type", "event_key", name="uq_notifications_task_type_event"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, name="notificationtype"),
        nullable=False,
    )
    # Overdue jobs share a stable key; every reassignment receives a new key.
    # This preserves idempotency without suppressing later reassignment events.
    event_key: Mapped[str] = mapped_column(String(64), nullable=False, default="legacy")
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    delivered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    task: Mapped["Task"] = relationship(  # noqa: F821
        "Task", back_populates="notifications", lazy="raise"
    )
    user: Mapped["User"] = relationship(  # noqa: F821
        "User", back_populates="notifications", lazy="raise"
    )

    def __repr__(self) -> str:
        return f"<Notification id={self.id} type={self.type} task_id={self.task_id}>"
