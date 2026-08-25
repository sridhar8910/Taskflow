import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import get_cached, invalidate_user_tasks, make_cache_key, set_cached
from app.database import get_db
from app.dependencies import get_current_user, get_redis
from app.models.task import TaskStatus
from app.models.user import User
from app.schemas.task import PaginatedTasksOut, TaskCreate, TaskOut, TaskUpdate
from app.services import task as task_service

router = APIRouter(tags=["tasks"])


def _enqueue_notifications_on_update(
    task_id: str,
    task_due_date,
    task_status: TaskStatus,
    old_assignee_id: uuid.UUID | None,
    new_assignee_id: uuid.UUID | None,
    owner_id: uuid.UUID,
) -> None:
    """
    Fire-and-forget notification jobs after a task update.
    - Reassignment: triggered when assignee changes.
    - Overdue: triggered when due_date < today and status != done.
    Both paths are idempotent at the worker level.
    """
    from datetime import date as date_type

    from app.worker.tasks import (
        send_overdue_notification,
        send_reassignment_notification,
    )

    # Reassignment notification
    if old_assignee_id != new_assignee_id:
        send_reassignment_notification.delay(
            task_id,
            str(old_assignee_id) if old_assignee_id else None,
            str(new_assignee_id) if new_assignee_id else None,
            str(uuid.uuid4()),
        )

    # Overdue notification (immediate check — Beat sweep is the periodic path)
    if (
        task_due_date is not None
        and task_due_date < date_type.today()
        and task_status != TaskStatus.done
    ):
        send_overdue_notification.delay(task_id, str(new_assignee_id or owner_id))


# ── Helpers ───────────────────────────────────────────────────────────────────


def _build_filter_dict(
    status: TaskStatus | None,
    assignee_id: uuid.UUID | None,
    due_date_from: date | None,
    due_date_to: date | None,
    project_id: uuid.UUID | None,
    page: int,
    page_size: int,
) -> dict:
    """Build a filter dict for cache key generation."""
    return {
        "status": status.value if status else None,
        "assignee_id": str(assignee_id) if assignee_id else None,
        "due_date_from": str(due_date_from) if due_date_from else None,
        "due_date_to": str(due_date_to) if due_date_to else None,
        "project_id": str(project_id) if project_id else None,
        "page": page,
        "page_size": page_size,
    }


async def _list_tasks_cached(
    db: AsyncSession,
    redis: Redis,
    owner_id: uuid.UUID,
    filters: dict,
    status_filter: TaskStatus | None,
    assignee_id: uuid.UUID | None,
    due_date_from: date | None,
    due_date_to: date | None,
    project_id: uuid.UUID | None,
    page: int,
    page_size: int,
) -> PaginatedTasksOut:
    """Cache-aside helper shared by both list endpoints."""
    key = make_cache_key(owner_id, filters)

    cached = await get_cached(redis, key)
    if cached is not None:
        return PaginatedTasksOut.model_validate_json(cached)

    result = await task_service.list_tasks(
        db=db,
        owner_id=owner_id,
        status_filter=status_filter,
        assignee_id=assignee_id,
        due_date_from=due_date_from,
        due_date_to=due_date_to,
        project_id=project_id,
        page=page,
        page_size=page_size,
    )
    await set_cached(redis, key, result.model_dump_json())
    return result


# ── Top-level GET /tasks ───────────────────────────────────────────────────────


@router.get(
    "/tasks",
    response_model=PaginatedTasksOut,
    summary="List all tasks for the current user (across all projects)",
)
async def list_all_tasks(
    status: TaskStatus | None = Query(
        default=None, description="Filter by task status"
    ),
    assignee_id: uuid.UUID | None = Query(
        default=None, description="Filter by assignee"
    ),
    due_date_from: date | None = Query(
        default=None, description="due_date >= this date"
    ),
    due_date_to: date | None = Query(default=None, description="due_date <= this date"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    limit: int | None = Query(
        default=None, ge=1, le=100, description="Alias for page_size"
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> PaginatedTasksOut:
    effective_page_size = limit if limit is not None else page_size
    filters = _build_filter_dict(
        status, assignee_id, due_date_from, due_date_to, None, page, effective_page_size
    )
    return await _list_tasks_cached(
        db,
        redis,
        current_user.id,
        filters,
        status,
        assignee_id,
        due_date_from,
        due_date_to,
        None,
        page,
        effective_page_size,
    )


# ── Project-scoped task routes ─────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/tasks",
    response_model=PaginatedTasksOut,
    summary="List tasks for a specific project",
)
async def list_project_tasks(
    project_id: uuid.UUID,
    status: TaskStatus | None = Query(default=None),
    assignee_id: uuid.UUID | None = Query(default=None),
    due_date_from: date | None = Query(default=None),
    due_date_to: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> PaginatedTasksOut:
    filters = _build_filter_dict(
        status, assignee_id, due_date_from, due_date_to, project_id, page, page_size
    )
    return await _list_tasks_cached(
        db,
        redis,
        current_user.id,
        filters,
        status,
        assignee_id,
        due_date_from,
        due_date_to,
        project_id,
        page,
        page_size,
    )


@router.post(
    "/projects/{project_id}/tasks",
    response_model=TaskOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a task in a project",
)
async def create_task(
    project_id: uuid.UUID,
    payload: TaskCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> TaskOut:
    task = await task_service.create_task(db, project_id, current_user.id, payload)
    # Invalidate owner's cache; if task has an assignee, invalidate theirs too
    await invalidate_user_tasks(redis, current_user.id, payload.assignee_id)
    return TaskOut.model_validate(task)


@router.get(
    "/projects/{project_id}/tasks/{task_id}",
    response_model=TaskOut,
    summary="Get a specific task",
)
async def get_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    task = await task_service.get_task_or_404(db, task_id, project_id, current_user.id)
    return TaskOut.model_validate(task)


@router.put(
    "/projects/{project_id}/tasks/{task_id}",
    response_model=TaskOut,
    summary="Update a task",
)
async def update_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: TaskUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> TaskOut:
    result = await task_service.update_task(
        db, task_id, project_id, current_user.id, payload
    )
    # Invalidate owner + old assignee + new assignee (handles reassignment correctly)
    await invalidate_user_tasks(
        redis,
        current_user.id,
        result.old_assignee_id,
        result.new_assignee_id,
    )
    # Enqueue background notification jobs (non-blocking)
    _enqueue_notifications_on_update(
        str(task_id),
        result.task.due_date,
        result.task.status,
        result.old_assignee_id,
        result.new_assignee_id,
        current_user.id,
    )
    return TaskOut.model_validate(result.task)


@router.delete(
    "/projects/{project_id}/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a task",
)
async def delete_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> None:
    # Capture assignee before deletion for cache invalidation
    task = await task_service.get_task_or_404(db, task_id, project_id, current_user.id)
    assignee_id = task.assignee_id
    await task_service.delete_task(db, task_id, project_id, current_user.id)
    await invalidate_user_tasks(redis, current_user.id, assignee_id)
