# Import all models so Alembic's autogenerate can discover them
from app.models.notification import Notification, NotificationType
from app.models.project import Project
from app.models.task import Task, TaskStatus
from app.models.user import User

__all__ = [
    "User",
    "Project",
    "Task",
    "TaskStatus",
    "Notification",
    "NotificationType",
]
