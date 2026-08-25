import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectUpdate


async def create_project(
    db: AsyncSession,
    owner_id: uuid.UUID,
    payload: ProjectCreate,
) -> Project:
    project = Project(
        owner_id=owner_id,
        name=payload.name,
        description=payload.description,
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)
    return project


async def list_projects(
    db: AsyncSession,
    owner_id: uuid.UUID,
) -> list[Project]:
    result = await db.execute(
        select(Project)
        .where(Project.owner_id == owner_id)
        .order_by(Project.created_at.desc())
    )
    return list(result.scalars().all())


async def get_project_or_404(
    db: AsyncSession,
    project_id: uuid.UUID,
    owner_id: uuid.UUID,
) -> Project:
    """
    Fetch a project by id.
    - Raises 404 if the project doesn't exist.
    - Raises 403 if it exists but belongs to a different user.
    This order prevents leaking the existence of other users' projects via timing.
    """
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )

    if project.owner_id != owner_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
        )

    return project


async def update_project(
    db: AsyncSession,
    project_id: uuid.UUID,
    owner_id: uuid.UUID,
    payload: ProjectUpdate,
) -> Project:
    project = await get_project_or_404(db, project_id, owner_id)

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(project, field, value)

    await db.flush()
    await db.refresh(project)
    return project


async def delete_project(
    db: AsyncSession,
    project_id: uuid.UUID,
    owner_id: uuid.UUID,
) -> None:
    project = await get_project_or_404(db, project_id, owner_id)
    await db.delete(project)
    await db.flush()
