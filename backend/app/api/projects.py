"""项目 CRUD 与 Agent 工作流触发。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import set_committed_value

from app.agents.graph import run_academic_workflow
from app.core.database import get_db
from app.core.security import get_current_user
from app.db.models import DraftVersion, Project, User
from app.models.schemas import (
    AgentRunRequest,
    DraftVersionOut,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
)
from app.services.literature_providers import default_database_ids, parse_database_ids
from app.services.literature_workflow import sync_literatures_from_zotero
from app.services.project_assembly import ensure_writing_ready

router = APIRouter(prefix="/projects", tags=["projects"])


async def _get_user_project(
    project_id: UUID, user: User, db: AsyncSession
) -> Project:
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id, Project.user_id == user.id)
        .options(
            selectinload(Project.literatures),
            selectinload(Project.draft_versions),
            selectinload(Project.source_documents),
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


def _derive_project_status(
    project: Project,
    *,
    literature_count: int,
    latest_version: int | None,
) -> str:
    """
    对外展示的进度状态（非「作业已交完」）。

    运行中保留瞬时态；其余按材料就绪度推导。旧 COMPLETED 视为已有草稿。
    """
    raw = (project.status or "").upper()
    if raw in ("FETCHING_PAPERS", "DRAFTING"):
        return raw
    if latest_version is not None or raw in ("HAS_DRAFT", "COMPLETED"):
        if latest_version is not None:
            return "HAS_DRAFT"
        # 库里曾标 COMPLETED 但草稿被删：继续往下推
    if literature_count > 0:
        return "LITERATURE_READY"
    if project.paper_outline and project.outline_locked_at:
        return "OUTLINE_LOCKED"
    if project.assessment_summary:
        return "INPUTS_IN_PROGRESS"
    return "INITIALIZING"


def _to_project_out(project: Project) -> ProjectOut:
    """将 Project ORM 转为响应（要求 literatures / draft_versions / source_documents 已加载）。"""
    literatures = project.__dict__.get("literatures") or []
    drafts = project.__dict__.get("draft_versions") or []
    sources = project.__dict__.get("source_documents") or []

    latest_version = max((d.version_number for d in drafts), default=None)
    literature_count = len(literatures)
    return ProjectOut(
        id=project.id,
        user_id=project.user_id,
        title=project.title,
        assessment_summary=project.assessment_summary,
        paper_outline=project.paper_outline,
        outline_locked_at=project.outline_locked_at,
        specific_requirements=project.specific_requirements,
        zotero_collection_id=project.zotero_collection_id,
        literature_databases=project.literature_databases,
        status=_derive_project_status(
            project,
            literature_count=literature_count,
            latest_version=latest_version,
        ),
        created_at=project.created_at,
        updated_at=project.updated_at,
        literature_count=literature_count,
        source_document_count=len(sources),
        latest_version=latest_version,
        outline_ready=bool(project.paper_outline and project.outline_locked_at),
        assessment_ready=bool(project.assessment_summary),
    )


def _mark_empty_collections(project: Project) -> None:
    """避免异步会话下对空关系的懒加载。"""
    set_committed_value(project, "literatures", [])
    set_committed_value(project, "draft_versions", [])
    set_committed_value(project, "source_documents", [])


@router.get("", response_model=List[ProjectOut])
async def list_projects(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[ProjectOut]:
    """列出当前用户全部项目。"""
    result = await db.execute(
        select(Project)
        .where(Project.user_id == current_user.id)
        .options(
            selectinload(Project.literatures),
            selectinload(Project.draft_versions),
            selectinload(Project.source_documents),
        )
        .order_by(Project.updated_at.desc())
    )
    projects = result.scalars().all()
    return [_to_project_out(p) for p in projects]


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    """创建项目。"""
    dbs = parse_database_ids(payload.literature_databases) or default_database_ids()
    try:
        from app.services.literature_providers import resolve_providers_for_project

        resolve_providers_for_project(dbs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    project = Project(
        user_id=current_user.id,
        title=payload.title,
        zotero_collection_id=payload.zotero_collection_id,
        literature_databases=dbs,
        status="INITIALIZING",
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)
    _mark_empty_collections(project)
    return _to_project_out(project)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    """获取项目详情。"""
    project = await _get_user_project(project_id, current_user, db)
    return _to_project_out(project)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: UUID,
    payload: ProjectUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    """更新项目字段。"""
    project = await _get_user_project(project_id, current_user, db)
    data = payload.model_dump(exclude_unset=True)
    if "literature_databases" in data:
        dbs = parse_database_ids(data["literature_databases"]) or default_database_ids()
        try:
            from app.services.literature_providers import resolve_providers_for_project

            resolve_providers_for_project(dbs)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        data["literature_databases"] = dbs
    for key, value in data.items():
        setattr(project, key, value)
    project.updated_at = datetime.now(timezone.utc)
    await db.flush()
    project = await _get_user_project(project_id, current_user, db)
    return _to_project_out(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """删除项目。"""
    project = await _get_user_project(project_id, current_user, db)
    await db.delete(project)


@router.post("/{project_id}/run-agent", response_model=DraftVersionOut)
async def run_agent(
    project_id: UUID,
    payload: AgentRunRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DraftVersionOut:
    """触发 LangGraph 学术写作工作流，并持久化文献与草稿版本。"""
    project = await _get_user_project(project_id, current_user, db)
    try:
        ensure_writing_ready(project)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    project.status = "FETCHING_PAPERS"
    await db.flush()

    assessment_text = project.assessment_summary or ""
    background_parts = [
        (d.summary_text or d.raw_text or "").strip()
        for d in (project.source_documents or [])
        if d.role == "BACKGROUND" and (d.summary_text or d.raw_text)
    ]
    paper_outline = project.paper_outline if isinstance(project.paper_outline, list) else []

    # 写作前以 Zotero 项目 Collection 为真源拉取（含离线新增）
    status_before = project.status
    project.status = "FETCHING_PAPERS"
    await db.flush()

    try:
        synced = await sync_literatures_from_zotero(project, db)
    except ValueError as exc:
        project.status = status_before
        await db.flush()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        project.status = status_before
        await db.flush()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        project.status = status_before
        await db.flush()
        raise HTTPException(status_code=502, detail=f"从 Zotero 拉取文献失败: {exc}") from exc

    sources_for_draft = [lit for lit in synced if lit.selected_for_draft]
    if not sources_for_draft:
        project.status = status_before
        await db.flush()
        raise HTTPException(
            status_code=400,
            detail=(
                "Zotero 项目集合中暂无文献。请先检索确认入库，"
                "或在 Zotero 客户端向该项目 Collection/章节子集合添加条目后重试"
            ),
        )

    existing_sources = [
        {
            "title": lit.title,
            "authors": lit.authors or [],
            "year": lit.year or "",
            "doi": lit.doi or "",
            "abstract": lit.abstract or "",
            "relevance_score": lit.relevance_score or 0.0,
            "zotero_item_key": lit.zotero_item_key,
        }
        for lit in sources_for_draft
    ]

    try:
        project.status = "DRAFTING"
        await db.flush()
        result = run_academic_workflow(
            project_id=str(project.id),
            assessment_summary=assessment_text,
            paper_outline=paper_outline,
            specific_requirements=project.specific_requirements or "",
            background_summaries=background_parts,
            max_papers=payload.max_papers,
            skip_search=True,
            zotero_collection_id=project.zotero_collection_id,
            existing_sources=existing_sources,
        )
    except Exception as exc:  # noqa: BLE001
        project.status = status_before
        await db.flush()
        raise HTTPException(status_code=500, detail=f"Agent 执行失败: {exc}") from exc

    _ = payload.skip_search

    ver_result = await db.execute(
        select(func.coalesce(func.max(DraftVersion.version_number), 0)).where(
            DraftVersion.project_id == project.id
        )
    )
    next_version = int(ver_result.scalar_one()) + 1
    draft = DraftVersion(
        project_id=project.id,
        version_number=next_version,
        content_markdown=result.get("draft_markdown") or "",
        apa_references_block=result.get("apa_references"),
        source_type="AGENT_GEN",
        changelog=(
            f"LangGraph 生成 v{next_version}; keywords={result.get('keywords')}; "
            f"writer={result.get('writer_mode') or 'template'}; "
            f"model={result.get('writer_model')}; "
            f"words≈{result.get('writer_word_count')}; "
            f"target={result.get('writer_word_target')}; "
            f"verify_ok={((result.get('writer_verification') or {}).get('ok'))}"
        ),
    )
    db.add(draft)
    # 有草稿 ≠ 作业完成；仅标记进度
    project.status = "HAS_DRAFT"
    project.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(draft)
    return draft
