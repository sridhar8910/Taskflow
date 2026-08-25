from celery import Celery

from app.config import settings

celery_app = Celery(
    "taskflow",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)

# Auto-discover tasks in app.worker.tasks
celery_app.autodiscover_tasks(["app.worker"])

# Import beat schedule AFTER celery_app is fully constructed to avoid
# circular import issues (beat_schedule imports celery_app).
import app.worker.beat_schedule  # noqa: E402, F401
