"""文献列表与 Zotero 相关接口。"""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import get_current_user
from app.db.models import Literature, Project, User
from app.models.schemas import (
    LiteratureImportRequest,
    LiteratureOut,
    LiteratureUpdate,
    ZoteroBindingRequest,
)
from app.services.literature_workflow import (
    bind_zotero_collection,
    ensure_zotero_structure,
    import_confirmed_items,
    sync_literatures_from_zotero,
)
from app.services.zotero_service import ZoteroService, zotero_service

router = APIRouter(prefix="/zotero", tags=["zotero"])


async def _assert_project_owner(
    project_id: UUID, user: User, db: AsyncSession
) -> Project:
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id, Project.user_id == user.id)
        .options(selectinload(Project.literatures))
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
    """列出默认库内集合（调试用）。"""
    _ = current_user
    if not zotero_service.is_configured:
        raise HTTPException(status_code=400, detail="Zotero 未配置")
    try:
        return {"collections": zotero_service.list_collections()}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Zotero 请求失败: {exc}") from exc


@router.get("/accessible-collections")
async def list_accessible_collections(
    current_user: User = Depends(get_current_user),
) -> dict:
    """聚合个人库 + 可访问 Groups 的顶层 Collections。"""
    _ = current_user
    try:
        return {"collections": zotero_service.list_accessible_top_collections()}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"列举 Collection 失败: {exc}") from exc


@router.get("/collections/{collection_key}/children")
async def list_collection_children(
    collection_key: str,
    library_type: Optional[str] = Query(None, pattern="^(user|group)$"),
    library_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
) -> dict:
    """列出指定库中某集合的直接子集合（Attach 入库下拉）。"""
    _ = current_user
    lib_type = (library_type or zotero_service.library_type or "user").strip()
    lib_id = (library_id or zotero_service.library_id or "").strip()
    if not lib_id:
        raise HTTPException(status_code=400, detail="需要 library_id")
    svc = ZoteroService(
        library_id=lib_id,
        library_type=lib_type,
        api_key=zotero_service.api_key,
    )
    if not svc.is_configured:
        raise HTTPException(status_code=400, detail="Zotero 未配置")
    try:
        children = svc.list_child_collections(collection_key)
        return {
            "collection_key": collection_key,
            "library_type": lib_type,
            "library_id": lib_id,
            "children": children,
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"列举子集合失败: {exc}") from exc


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


@router.post("/projects/{project_id}/binding")
async def set_zotero_binding(
    project_id: UUID,
    payload: ZoteroBindingRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """绑定：create 新建结构，或 attach 已有集合并全量 sync。"""
    project = await _assert_project_owner(project_id, current_user, db)
    try:
        result = await bind_zotero_collection(
            project,
            db,
            mode=payload.mode,
            collection_key=payload.collection_key,
            library_type=payload.library_type,
            library_id=payload.library_id,
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Zotero 绑定失败: {exc}") from exc


@router.post("/projects/{project_id}/ensure-structure")
async def ensure_structure(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建/对齐项目顶层 Collection + 章节 Subcollections（仅 create）。"""
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
    project = await _assert_project_owner(project_id, current_user, db)
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
    """确认文献：写入 Zotero 并镜像本地。"""
    project = await _assert_project_owner(project_id, current_user, db)
    if (project.zotero_binding_mode or "").strip().lower() == "attach":
        raise HTTPException(
            status_code=400,
            detail="attach 模式请使用章节分配，不可从平台向 Zotero 写入新条目",
        )
    if not payload.items:
        raise HTTPException(status_code=400, detail="items 不能为空")
    try:
        created = await import_confirmed_items(
            project,
            db,
            outline_heading=payload.outline_heading,
            items=[item.model_dump() for item in payload.items],
            source_query=payload.source_query,
            target_collection_key=payload.target_collection_key,
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
    """列出项目文献库（含 assigned_headings / collection_path）。"""
    project = await _assert_project_owner(project_id, current_user, db)
    from app.services.literature_assignments import list_literatures_enriched

    return await list_literatures_enriched(project, db)


@router.patch("/literatures/{literature_id}", response_model=LiteratureOut)
async def update_literature(
    literature_id: UUID,
    payload: LiteratureUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LiteratureOut:
    """更新文献选中状态或相关度。"""
    from app.services.literature_assignments import list_literatures_enriched

    result = await db.execute(select(Literature).where(Literature.id == literature_id))
    lit = result.scalar_one_or_none()
    if not lit:
        raise HTTPException(status_code=404, detail="文献不存在")
    project = await _assert_project_owner(lit.project_id, current_user, db)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(lit, key, value)
    await db.flush()
    await db.refresh(lit)
    enriched = await list_literatures_enriched(project, db, literatures=[lit])
    return enriched[0]
