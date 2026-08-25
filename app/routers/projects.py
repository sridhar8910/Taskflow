import uuid

from fastapi import APIRouter, Depends, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import invalidate_user_tasks
from app.database import get_db
from app.dependencies import get_current_user, get_redis
from app.models.user import User
from app.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate
from app.services import project as project_service

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get(
    "",
    response_model=list[ProjectOut],
    summary="List all projects owned by the current user",
)
async def list_projects(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ProjectOut]:
    projects = await project_service.list_projects(db, current_user.id)
    return [ProjectOut.model_validate(p) for p in projects]


@router.post(
    "",
    response_model=ProjectOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new project",
)
async def create_project(
    payload: ProjectCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    project = await project_service.create_project(db, current_user.id, payload)
    return ProjectOut.model_validate(project)


@router.get("/{project_id}", response_model=ProjectOut, summary="Get a project by ID")
async def get_project(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    project = await project_service.get_project_or_404(db, project_id, current_user.id)
    return ProjectOut.model_validate(project)


@router.put("/{project_id}", response_model=ProjectOut, summary="Update a project")
async def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    project = await project_service.update_project(
        db, project_id, current_user.id, payload
    )
    return ProjectOut.model_validate(project)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project",
)
async def delete_project(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> None:
    await project_service.delete_project(db, project_id, current_user.id)
    await invalidate_user_tasks(redis, current_user.id)
