import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.notification import NotificationType


class NotificationOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    user_id: uuid.UUID
    type: NotificationType
    message: str
    delivered: bool
    is_read: bool = False
    read: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}

    from pydantic import model_validator

    @model_validator(mode="before")
    @classmethod
    def populate_read_flags(cls, data: any) -> any:
        if hasattr(data, "delivered"):
            read_val = getattr(data, "delivered", False)
            if isinstance(data, dict):
                data["is_read"] = read_val
                data["read"] = read_val
            else:
                # Attach dynamically if ORM model instance
                setattr(data, "is_read", read_val)
                setattr(data, "read", read_val)
        return data
