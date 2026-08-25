"""
Celery task definitions for TaskFlow notifications.

Design decisions:
- Tasks use a synchronous SQLAlchemy session (separate from the async app engine).
  This avoids the complexity of running an asyncio event loop inside Celery workers.
- Idempotency is enforced at the DB level via a UNIQUE constraint on
  (task_id, type) in the notifications table. The get_or_create pattern here
  handles the application-level check; the DB constraint is the final guard.
- Notification "delivery" is simulated by writing to the log and the DB.
"""

import logging
import uuid

from sqlalchemy.exc import IntegrityError

from app.database import get_sync_db
from app.models.notification import Notification, NotificationType
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


def _get_or_create_notification(
    task_id: uuid.UUID,
    user_id: uuid.UUID,
    notification_type: NotificationType,
    event_key: str,
    message: str,
) -> tuple[Notification, bool]:
    """
    Fetch an existing notification of (task_id, type) or create a new one.
    Returns (notification, created: bool).

    The UNIQUE constraint on (task_id, type) in the DB is the authoritative
    idempotency guard; this function is the optimistic fast path.
    """
    from sqlalchemy import select

    db = None
    try:
        db = get_sync_db()
        existing = db.execute(
            select(Notification).where(
                Notification.task_id == task_id,
                Notification.type == notification_type,
                Notification.event_key == event_key,
            )
        ).scalar_one_or_none()

        if existing is not None:
            return existing, False

        notification = Notification(
            task_id=task_id,
            user_id=user_id,
            type=notification_type,
            event_key=event_key,
            message=message,
            delivered=False,
        )
        db.add(notification)
        db.commit()
        db.refresh(notification)
        return notification, True
    except IntegrityError:
        # Race condition: another worker created the same notification concurrently.
        if db is not None:
            db.rollback()
        db2 = get_sync_db()
        try:
            existing = db2.execute(
                select(Notification).where(
                    Notification.task_id == task_id,
                    Notification.type == notification_type,
                    Notification.event_key == event_key,
                )
            ).scalar_one()
            return existing, False
        finally:
            db2.close()
    finally:
        if db is not None:
            db.close()


@celery_app.task(
    name="app.worker.tasks.send_reassignment_notification", bind=True, max_retries=3
)
def send_reassignment_notification(
    self,
    task_id: str,
    old_assignee_id: str | None,
    new_assignee_id: str | None,
    event_id: str | None = None,
) -> dict:
    """
    Create a reassignment notification for the new assignee.
    Idempotent: calling with the same task_id a second time is a no-op.
    """
    task_uuid = uuid.UUID(task_id)
    new_uuid = uuid.UUID(new_assignee_id) if new_assignee_id else None

    if new_uuid is None:
        logger.info(
            "send_reassignment_notification: no new assignee for task %s, skipping",
            task_id,
        )
        return {"skipped": True}

    message = (
        f"Task {task_id} has been reassigned to you"
        + (f" from {old_assignee_id}" if old_assignee_id else "")
        + "."
    )

    try:
        event_key = event_id or f"legacy:{old_assignee_id}:{new_assignee_id}"
        notification, created = _get_or_create_notification(
            task_uuid, new_uuid, NotificationType.reassigned, event_key, message
        )
    except Exception as exc:
        logger.exception("send_reassignment_notification failed for task %s", task_id)
        raise self.retry(exc=exc, countdown=5)

    if created:
        # Simulated delivery — in production this would be email/webhook/push
        logger.info(
            "[NOTIFICATION DELIVERED] reassigned | task=%s | to=%s",
            task_id,
            new_assignee_id,
        )
    else:
        logger.debug("[NOTIFICATION SKIPPED — duplicate] reassigned | task=%s", task_id)

    return {"notification_id": str(notification.id), "created": created}


@celery_app.task(
    name="app.worker.tasks.send_overdue_notification", bind=True, max_retries=3
)
def send_overdue_notification(
    self,
    task_id: str,
    assignee_id: str | None,
) -> dict:
    """
    Create an overdue notification for the task's assignee (or project owner
    if unassigned — resolved at call site).
    Idempotent: calling with the same task_id a second time is a no-op.
    """
    task_uuid = uuid.UUID(task_id)
    user_uuid = uuid.UUID(assignee_id) if assignee_id else None

    if user_uuid is None:
        logger.info(
            "send_overdue_notification: no assignee for task %s, skipping", task_id
        )
        return {"skipped": True}

    message = f"Task {task_id} is overdue and has not been marked as done."

    try:
        notification, created = _get_or_create_notification(
            task_uuid, user_uuid, NotificationType.overdue, "overdue", message
        )
    except Exception as exc:
        logger.exception("send_overdue_notification failed for task %s", task_id)
        raise self.retry(exc=exc, countdown=5)

    if created:
        logger.info(
            "[NOTIFICATION DELIVERED] overdue | task=%s | assignee=%s",
            task_id,
            assignee_id,
        )
    else:
        logger.debug("[NOTIFICATION SKIPPED — duplicate] overdue | task=%s", task_id)

    return {"notification_id": str(notification.id), "created": created}


@celery_app.task(name="app.worker.tasks.check_overdue_tasks")
def check_overdue_tasks() -> dict:
    """
    Periodic sweep (run by Celery Beat every 60 seconds).

    Finds all tasks where:
      - due_date < date.today()
      - status != done
      - no overdue notification row already exists

    Enqueues send_overdue_notification for each match.
    The idempotency guard in send_overdue_notification makes double-sweeps safe.

    Uses a synchronous SQLAlchemy session — this task runs inside the Celery
    worker process, outside the async FastAPI context.
    """
    from datetime import date

    from sqlalchemy import select

    from app.models.notification import Notification, NotificationType
    from app.models.task import Task, TaskStatus

    db = get_sync_db()
    enqueued = 0

    try:
        today = date.today()

        # Find tasks that are overdue AND don't already have an overdue notification

        overdue_tasks = (
            db.execute(
                select(Task).where(
                    Task.due_date < today,
                    Task.status != TaskStatus.done,
                    ~Task.id.in_(
                        select(Notification.task_id).where(
                            Notification.type == NotificationType.overdue
                        )
                    ),
                )
            )
            .scalars()
            .all()
        )

        for task in overdue_tasks:
            if task.assignee_id is not None:
                send_overdue_notification.delay(str(task.id), str(task.assignee_id))
                enqueued += 1
                logger.info(
                    "[BEAT SWEEP] Enqueued overdue notification | task=%s | assignee=%s",
                    task.id,
                    task.assignee_id,
                )

    finally:
        db.close()

    logger.info("[BEAT SWEEP] check_overdue_tasks complete | enqueued=%d", enqueued)
    return {"enqueued": enqueued}
