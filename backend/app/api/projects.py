"""项目 CRUD 与 Agent 工作流触发。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.graph import run_academic_workflow
from app.core.database import get_db
from app.core.security import get_current_user
from app.db.models import DraftVersion, Literature, NotebookLMInput, Project, User
from app.models.schemas import (
    AgentRunRequest,
    DraftVersionOut,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
)

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
            selectinload(Project.notebook_inputs),
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


def _to_project_out(project: Project) -> ProjectOut:
    latest_version = None
    if project.draft_versions:
        latest_version = max(d.version_number for d in project.draft_versions)
    latest_sync = None
    if project.notebook_inputs:
        latest_sync = max(n.synced_at for n in project.notebook_inputs)
    return ProjectOut(
        id=project.id,
        user_id=project.user_id,
        title=project.title,
        assessment_requirements=project.assessment_requirements,
        zotero_collection_id=project.zotero_collection_id,
        status=project.status,
        created_at=project.created_at,
        updated_at=project.updated_at,
        literature_count=len(project.literatures or []),
        latest_version=latest_version,
        latest_sync_at=latest_sync,
    )


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
            selectinload(Project.notebook_inputs),
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
    project = Project(
        user_id=current_user.id,
        title=payload.title,
        assessment_requirements=payload.assessment_requirements,
        zotero_collection_id=payload.zotero_collection_id,
        status="INITIALIZING",
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)
    project.literatures = []
    project.draft_versions = []
    project.notebook_inputs = []
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
    for key, value in data.items():
        setattr(project, key, value)
    project.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(project)
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
    project.status = "FETCHING_PAPERS"
    await db.flush()

    notebook_context = ""
    if project.notebook_inputs:
        latest = max(project.notebook_inputs, key=lambda n: n.synced_at)
        notebook_context = latest.extracted_summary or latest.raw_transcript or ""

    existing_sources = None
    if payload.skip_search and project.literatures:
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
            for lit in project.literatures
            if lit.selected_for_draft
        ]

    try:
        project.status = "DRAFTING"
        await db.flush()
        result = run_academic_workflow(
            project_id=str(project.id),
            assessment_requirements=project.assessment_requirements or "",
            notebook_context=notebook_context,
            max_papers=payload.max_papers,
            skip_search=payload.skip_search,
            zotero_collection_id=project.zotero_collection_id,
            existing_sources=existing_sources,
        )
    except Exception as exc:  # noqa: BLE001
        project.status = "INITIALIZING"
        await db.flush()
        raise HTTPException(status_code=500, detail=f"Agent 执行失败: {exc}") from exc

    # 持久化文献（非 skip_search 时替换选中集）
    if not payload.skip_search:
        for lit in list(project.literatures):
            await db.delete(lit)
        await db.flush()
        for src in result.get("sources") or []:
            db.add(
                Literature(
                    project_id=project.id,
                    zotero_item_key=src.get("zotero_item_key"),
                    title=src.get("title") or "Untitled",
                    authors=src.get("authors"),
                    year=src.get("year"),
                    doi=src.get("doi"),
                    abstract=src.get("abstract"),
                    relevance_score=src.get("relevance_score"),
                    selected_for_draft=True,
                )
            )

    # 新版本号
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
        changelog=f"LangGraph 生成 v{next_version}; keywords={result.get('keywords')}",
    )
    db.add(draft)
    project.status = "COMPLETED"
    project.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(draft)
    return draft
