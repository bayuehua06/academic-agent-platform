"""文献检索 API：AUT→IEEE / ACM；多库各取 max_results 后去重。"""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.db.models import Project, User
from app.models.schemas import LiteratureOut
from app.services.acm_aut_search import acm_aut_search_service
from app.services.ieee_aut_search import ieee_aut_search_service
from app.services.literature_providers import (
    list_providers,
    parse_database_ids,
    resolve_providers_for_project,
)
from app.services.literature_search_store import literature_search_store
from app.services.literature_workflow import (
    annotate_candidates_against_library,
    dedupe_candidates,
    import_confirmed_items,
)
from app.services.zotero_service import zotero_service

router = APIRouter(tags=["literature-search"])
settings = get_settings()

_SEARCH_SERVICES = {
    "ieee": ieee_aut_search_service,
    "acm": acm_aut_search_service,
}


class LiteratureSearchRequest(BaseModel):
    """触发一次检索。"""

    outline_heading: str = Field(..., min_length=1)
    query: Optional[str] = None
    max_results: int = Field(10, ge=1, le=30)
    databases: Optional[List[str]] = None  # 覆盖项目勾选；默认用项目配置


class LiteratureConfirmRequest(BaseModel):
    """确认入库：按候选下标勾选。"""

    indices: List[int] = Field(..., min_length=1)


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


async def _library_snapshot_for_project(project: Project, db: AsyncSession) -> list:
    """
    获取项目已有文献快照（优先只读拉取 Zotero；失败则用本地镜像）。

    不做全量 sync，避免检索时改写本地库。
    """
    _ = db
    if project.zotero_collection_id and zotero_service.is_configured:
        try:
            remote = zotero_service.fetch_project_collection_items(
                project.zotero_collection_id
            )
            if remote:
                return remote
        except Exception as exc:  # noqa: BLE001
            _ = exc
    return list(project.literatures or [])


@router.get("/literature-providers")
async def get_literature_providers(
    current_user: User = Depends(get_current_user),
) -> dict:
    """列出全局检索库注册表（来自 .env）。"""
    _ = current_user
    return {"providers": list_providers()}


@router.post("/projects/{project_id}/literature-search/ping")
async def literature_search_ping(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """探测项目启用库的连通性。"""
    project = await _assert_project_owner(project_id, current_user, db)
    try:
        providers = resolve_providers_for_project(project.literature_databases)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    results = []
    overall_ok = True
    for provider in providers:
        svc = _SEARCH_SERVICES.get(provider.id)
        if svc is not None and provider.implemented:
            ping = await svc.ping()
            results.append(ping)
            overall_ok = overall_ok and bool(ping.get("ok"))
        elif not provider.implemented:
            results.append(
                {
                    "ok": False,
                    "provider": provider.id,
                    "configured": True,
                    "error": f"{provider.name} 尚未实现（已注册入口，后续接入）",
                }
            )
            overall_ok = False
        else:
            results.append(
                {
                    "ok": False,
                    "provider": provider.id,
                    "error": "未知实现",
                }
            )
            overall_ok = False
    return {"ok": overall_ok, "results": results}


@router.post("/projects/{project_id}/literature-search")
async def literature_search(
    project_id: UUID,
    payload: LiteratureSearchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    执行检索，返回 run + candidates（尚未写入 literatures）。

    多库时每个库各取 max_results 条，再按 DOI/标题去重。
    query 为空时使用 LITERATURE_TEST_QUERY。
    """
    project = await _assert_project_owner(project_id, current_user, db)
    heading = payload.outline_heading.strip()
    outline = project.paper_outline if isinstance(project.paper_outline, list) else []
    headings = {
        (item.get("heading") or "").strip()
        for item in outline
        if isinstance(item, dict)
    }
    if headings and heading not in headings:
        raise HTTPException(status_code=400, detail=f"大纲中不存在章节: {heading!r}")

    query = (payload.query or "").strip() or (settings.literature_test_query or "").strip()
    if not query:
        raise HTTPException(
            status_code=400,
            detail="未提供 query，且未配置 LITERATURE_TEST_QUERY",
        )

    db_ids = payload.databases
    if db_ids is None:
        db_ids = project.literature_databases
    try:
        providers = resolve_providers_for_project(db_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    candidates: list = []
    errors: list = []
    used: list = []
    for provider in providers:
        svc = _SEARCH_SERVICES.get(provider.id)
        if svc is None or not provider.implemented:
            errors.append(
                {
                    "provider": provider.id,
                    "error": f"{provider.name} 尚未实现"
                    if not provider.implemented
                    else "未知实现",
                }
            )
            continue
        try:
            used.append(provider.id)
            # 每个库各自取 max_results，再统一去重
            batch = await svc.search(query, max_results=payload.max_results)
            for item in batch:
                item["outline_heading"] = heading
                item["source_query"] = query
            candidates.extend(batch)
        except Exception as exc:  # noqa: BLE001
            errors.append({"provider": provider.id, "error": str(exc)})

    before_dedupe = len(candidates)
    candidates = dedupe_candidates(candidates)
    deduped_count = before_dedupe - len(candidates)

    existing = await _library_snapshot_for_project(project, db)
    candidates = annotate_candidates_against_library(candidates, existing)

    status = "completed" if candidates else ("failed" if errors else "completed")
    run = literature_search_store.create(
        project_id=str(project.id),
        outline_heading=heading,
        query=query,
        providers=used or parse_database_ids(db_ids),
        candidates=candidates,
        status=status,
        error="; ".join(e["error"] for e in errors) if errors and not candidates else None,
    )
    if not candidates and errors:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "检索失败",
                "errors": errors,
                "run_id": run["id"],
            },
        )
    return {
        **run,
        "partial_errors": errors or None,
        "deduped_count": deduped_count or None,
    }


@router.get("/projects/{project_id}/literature-search/{run_id}")
async def get_literature_search_run(
    project_id: UUID,
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """取回一次检索 run（进程内内存；重启后失效）。"""
    await _assert_project_owner(project_id, current_user, db)
    run = literature_search_store.get(run_id)
    if not run or run.get("project_id") != str(project_id):
        raise HTTPException(status_code=404, detail="检索结果不存在或已过期")
    return run


@router.post("/projects/{project_id}/literature-search/{run_id}/confirm")
async def confirm_literature_search(
    project_id: UUID,
    run_id: str,
    payload: LiteratureConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[LiteratureOut]:
    """将勾选的候选写入 Zotero 章节子集合 + 本地 literatures。"""
    project = await _assert_project_owner(project_id, current_user, db)
    run = literature_search_store.get(run_id)
    if not run or run.get("project_id") != str(project_id):
        raise HTTPException(status_code=404, detail="检索结果不存在或已过期")

    candidates = run.get("candidates") or []
    selected: list = []
    for idx in payload.indices:
        if idx < 0 or idx >= len(candidates):
            raise HTTPException(status_code=400, detail=f"无效下标: {idx}")
        selected.append(candidates[idx])

    try:
        created = await import_confirmed_items(
            project,
            db,
            outline_heading=run["outline_heading"],
            items=selected,
            source_query=run.get("query") or "",
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"入库失败: {exc}") from exc

    await db.commit()
    for row in created:
        await db.refresh(row)
    return [LiteratureOut.model_validate(row) for row in created]
