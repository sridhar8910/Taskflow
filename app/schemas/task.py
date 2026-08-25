import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.task import TaskStatus


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    assignee_id: uuid.UUID | None = None
    due_date: date | None = None
    status: TaskStatus = TaskStatus.todo


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    assignee_id: uuid.UUID | None = None
    due_date: date | None = None
    status: TaskStatus | None = None


class TaskOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    assignee_id: uuid.UUID | None
    title: str
    description: str | None
    due_date: date | None
    status: TaskStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PaginatedTasksOut(BaseModel):
    items: list[TaskOut]
    total: int
    page: int
    page_size: int
    pages: int
