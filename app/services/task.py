import math
import uuid
from dataclasses import dataclass
from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.task import Task, TaskStatus
from app.schemas.task import PaginatedTasksOut, TaskCreate, TaskOut, TaskUpdate
from app.services.project import get_project_or_404

# Maximum page size to prevent runaway queries
MAX_PAGE_SIZE = 100


@dataclass
class TaskMutationResult:
    """Returned by update_task so callers can act on assignee changes."""

    task: Task
    old_assignee_id: uuid.UUID | None
    new_assignee_id: uuid.UUID | None


async def _validate_assignee_exists(
    db: AsyncSession, assignee_id: uuid.UUID | None
) -> None:
    if assignee_id is not None:
        from app.models.user import User

        res = await db.execute(select(User).where(User.id == assignee_id))
        if res.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Assignee user {assignee_id} does not exist",
            )


async def create_task(
    db: AsyncSession,
    project_id: uuid.UUID,
    owner_id: uuid.UUID,
    payload: TaskCreate,
) -> Task:
    # Verify project ownership before creating the task
    await get_project_or_404(db, project_id, owner_id)
    await _validate_assignee_exists(db, payload.assignee_id)

    task = Task(
        project_id=project_id,
        assignee_id=payload.assignee_id,
        title=payload.title,
        description=payload.description,
        due_date=payload.due_date,
        status=payload.status,
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return task


async def get_task_or_404(
    db: AsyncSession,
    task_id: uuid.UUID,
    project_id: uuid.UUID,
    owner_id: uuid.UUID,
) -> Task:
    """
    Fetch a task by id within a project.
    Raises 404 if not found, 403 if the project isn't owned by owner_id.
    """
    # Verify project ownership first
    await get_project_or_404(db, project_id, owner_id)

    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.project_id == project_id)
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
        )
    return task


async def update_task(
    db: AsyncSession,
    task_id: uuid.UUID,
    project_id: uuid.UUID,
    owner_id: uuid.UUID,
    payload: TaskUpdate,
) -> TaskMutationResult:
    task = await get_task_or_404(db, task_id, project_id, owner_id)

    if payload.assignee_id is not None:
        await _validate_assignee_exists(db, payload.assignee_id)

    old_assignee_id = task.assignee_id
    update_data = payload.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(task, field, value)

    new_assignee_id = task.assignee_id

    await db.flush()
    await db.refresh(task)
    return TaskMutationResult(
        task=task,
        old_assignee_id=old_assignee_id,
        new_assignee_id=new_assignee_id,
    )


async def delete_task(
    db: AsyncSession,
    task_id: uuid.UUID,
    project_id: uuid.UUID,
    owner_id: uuid.UUID,
) -> None:
    task = await get_task_or_404(db, task_id, project_id, owner_id)
    await db.delete(task)
    await db.flush()


async def list_tasks(
    db: AsyncSession,
    owner_id: uuid.UUID,
    status_filter: TaskStatus | None = None,
    assignee_id: uuid.UUID | None = None,
    due_date_from: date | None = None,
    due_date_to: date | None = None,
    project_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PaginatedTasksOut:
    """
    List tasks visible to owner_id (i.e. tasks in projects they own or tasks assigned to them).
    Supports filtering by status, assignee, date range, and project.
    Returns paginated results.
    """
    page_size = min(page_size, MAX_PAGE_SIZE)
    page = max(page, 1)
    offset = (page - 1) * page_size

    # Base query: tasks in projects owned by this user OR assigned to this user
    base_query = (
        select(Task)
        .join(Project, Task.project_id == Project.id)
        .where((Project.owner_id == owner_id) | (Task.assignee_id == owner_id))
    )

    # Optional filters
    if project_id is not None:
        base_query = base_query.where(Task.project_id == project_id)
    if status_filter is not None:
        base_query = base_query.where(Task.status == status_filter)
    if assignee_id is not None:
        base_query = base_query.where(Task.assignee_id == assignee_id)
    if due_date_from is not None:
        base_query = base_query.where(Task.due_date >= due_date_from)
    if due_date_to is not None:
        base_query = base_query.where(Task.due_date <= due_date_to)

    # Count total before pagination
    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    # Fetch page
    paginated_query = (
        base_query.order_by(Task.created_at.desc()).offset(offset).limit(page_size)
    )
    result = await db.execute(paginated_query)
    tasks = list(result.scalars().all())

    pages = math.ceil(total / page_size) if total > 0 else 1

    return PaginatedTasksOut(
        items=[TaskOut.model_validate(t) for t in tasks],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )
