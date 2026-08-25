"""Allow distinct reassignment notification events for one task.

Revision ID: 7f31d0f52a9b
Revises: 20bec4e4cdd4
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7f31d0f52a9b"
down_revision: str | None = "20bec4e4cdd4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("event_key", sa.String(64), nullable=True))
    op.execute(
        "UPDATE notifications SET event_key = CASE "
        "WHEN type = 'overdue' THEN 'overdue' "
        "ELSE 'legacy-' || id::text END"
    )
    op.alter_column("notifications", "event_key", nullable=False)
    op.drop_constraint("uq_notifications_task_type", "notifications", type_="unique")
    op.create_unique_constraint(
        "uq_notifications_task_type_event",
        "notifications",
        ["task_id", "type", "event_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_notifications_task_type_event", "notifications", type_="unique"
    )
    op.create_unique_constraint(
        "uq_notifications_task_type", "notifications", ["task_id", "type"]
    )
    op.drop_column("notifications", "event_key")
