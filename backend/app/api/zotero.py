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
from app.models.schemas import (
    LiteratureImportRequest,
    LiteratureOut,
    LiteratureUpdate,
)
from app.services.literature_workflow import (
    ensure_zotero_structure,
    import_confirmed_items,
    sync_literatures_from_zotero,
)
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


@router.get("/ping")
async def zotero_ping(
    current_user: User = Depends(get_current_user),
) -> dict:
    """真实连通检测 Zotero API。"""
    _ = current_user
    return zotero_service.ping()


@router.get("/collections")
async def list_zotero_collections(
    current_user: User = Depends(get_current_user),
) -> dict:
    """列出库内集合（调试用）。"""
    _ = current_user
    if not zotero_service.is_configured:
        raise HTTPException(status_code=400, detail="Zotero 未配置")
    try:
        return {"collections": zotero_service.list_collections()}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Zotero 请求失败: {exc}") from exc


@router.get("/status")
async def zotero_status(
    current_user: User = Depends(get_current_user),
) -> dict:
    """检查 Zotero API 是否已配置（不发真实请求）。"""
    _ = current_user
    return {
        "configured": zotero_service.is_configured,
        "library_type": zotero_service.library_type if zotero_service.is_configured else None,
    }


@router.post("/projects/{project_id}/ensure-structure")
async def ensure_structure(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建/对齐项目顶层 Collection + 章节 Subcollections。"""
    project = await _assert_project_owner(project_id, current_user, db)
    try:
        return await ensure_zotero_structure(project, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Zotero 结构对齐失败: {exc}") from exc


@router.post("/projects/{project_id}/sync", response_model=List[LiteratureOut])
async def sync_from_zotero(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[LiteratureOut]:
    """
    从 Zotero 项目 Collection（含章节子集合）拉取并覆盖本地镜像。

    离线在 Zotero 中增删后，点此同步；写作 Agent 也会在运行前自动拉取。
    """
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(Project)
        .where(Project.id == project_id, Project.user_id == current_user.id)
        .options(selectinload(Project.literatures))
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    try:
        return await sync_literatures_from_zotero(project, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Zotero 同步失败: {exc}") from exc


@router.post("/projects/{project_id}/import", response_model=List[LiteratureOut])
async def import_literatures(
    project_id: UUID,
    payload: LiteratureImportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[LiteratureOut]:
    """确认文献：写入 Zotero 章节子集合并镜像本地。"""
    project = await _assert_project_owner(project_id, current_user, db)
    if not payload.items:
        raise HTTPException(status_code=400, detail="items 不能为空")
    try:
        created = await import_confirmed_items(
            project,
            db,
            outline_heading=payload.outline_heading,
            items=[item.model_dump() for item in payload.items],
            source_query=payload.source_query,
        )
        return created
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"文献入库失败: {exc}") from exc



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
