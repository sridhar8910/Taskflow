"""
Celery Beat periodic schedule.

The overdue sweep runs every 60 seconds. It finds all tasks where:
  - due_date < today  (date comparison, not datetime)
  - status != done
  - no overdue notification row already exists

For each match it enqueues send_overdue_notification, which is itself
idempotent via the UNIQUE(task_id, type) DB constraint.
"""

from app.worker.celery_app import celery_app

celery_app.conf.beat_schedule = {
    "check-overdue-tasks-every-60s": {
        "task": "app.worker.tasks.check_overdue_tasks",
        "schedule": 60.0,  # seconds
    },
}

celery_app.conf.timezone = "UTC"
