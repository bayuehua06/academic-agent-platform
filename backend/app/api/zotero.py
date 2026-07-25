"""文献列表与 Zotero 相关接口。"""

from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.db.models import Literature, Project, User
from app.models.schemas import LiteratureOut, LiteratureUpdate
from app.services.zotero_service import zotero_service

router = APIRouter(prefix="/zotero", tags=["zotero"])


async def _assert_project_owner(
    project_id: UUID, user: User, db: AsyncSession
) -> Project:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


@router.get("/projects/{project_id}/literatures", response_model=List[LiteratureOut])
async def list_literatures(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[LiteratureOut]:
    """列出项目文献库。"""
    await _assert_project_owner(project_id, current_user, db)
    result = await db.execute(
        select(Literature)
        .where(Literature.project_id == project_id)
        .order_by(Literature.relevance_score.desc().nullslast())
    )
    return list(result.scalars().all())


@router.patch("/literatures/{literature_id}", response_model=LiteratureOut)
async def update_literature(
    literature_id: UUID,
    payload: LiteratureUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LiteratureOut:
    """更新文献选中状态或相关度。"""
    result = await db.execute(select(Literature).where(Literature.id == literature_id))
    lit = result.scalar_one_or_none()
    if not lit:
        raise HTTPException(status_code=404, detail="文献不存在")
    await _assert_project_owner(lit.project_id, current_user, db)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(lit, key, value)
    await db.flush()
    await db.refresh(lit)
    return lit


@router.get("/status")
async def zotero_status(
    current_user: User = Depends(get_current_user),
) -> dict:
    """检查 Zotero API 是否已配置。"""
    return {
        "configured": zotero_service.is_configured,
        "library_type": zotero_service.library_type if zotero_service.is_configured else None,
    }
