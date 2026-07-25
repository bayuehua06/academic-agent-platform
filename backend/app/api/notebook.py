"""NotebookLM 输入同步接口。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.db.models import NotebookLMInput, Project, User
from app.models.schemas import NotebookLMCreate, NotebookLMOut, NotebookLMSyncRequest
from app.services.notebooklm import notebooklm_service

router = APIRouter(prefix="/notebook", tags=["notebook"])


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


@router.get("/{project_id}", response_model=List[NotebookLMOut])
async def list_inputs(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[NotebookLMOut]:
    """列出项目的 NotebookLM 输入记录。"""
    await _assert_project_owner(project_id, current_user, db)
    result = await db.execute(
        select(NotebookLMInput)
        .where(NotebookLMInput.project_id == project_id)
        .order_by(NotebookLMInput.synced_at.desc())
    )
    return list(result.scalars().all())


@router.post("/{project_id}", response_model=NotebookLMOut, status_code=status.HTTP_201_CREATED)
async def create_input(
    project_id: UUID,
    payload: NotebookLMCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotebookLMOut:
    """MVP：手动粘贴 transcript / summary。"""
    await _assert_project_owner(project_id, current_user, db)
    raw = payload.raw_transcript or ""
    summary = payload.extracted_summary or notebooklm_service.extract_summary(raw)
    record = NotebookLMInput(
        project_id=project_id,
        notebook_url=payload.notebook_url,
        raw_transcript=raw or None,
        extracted_summary=summary or None,
        synced_at=datetime.now(timezone.utc),
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)
    return record


@router.post("/{project_id}/upload", response_model=NotebookLMOut, status_code=status.HTTP_201_CREATED)
async def upload_markdown(
    project_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotebookLMOut:
    """上传 Markdown 文件作为 NotebookLM 输入。"""
    await _assert_project_owner(project_id, current_user, db)
    content = (await file.read()).decode("utf-8", errors="replace")
    raw, summary = notebooklm_service.parse_markdown_file(content)
    record = NotebookLMInput(
        project_id=project_id,
        raw_transcript=raw,
        extracted_summary=summary,
        synced_at=datetime.now(timezone.utc),
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)
    return record


@router.post("/{project_id}/sync", response_model=NotebookLMOut)
async def sync_notebook(
    project_id: UUID,
    payload: NotebookLMSyncRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotebookLMOut:
    """扩展：Playwright 自动抓取（未启用时返回 501）。"""
    await _assert_project_owner(project_id, current_user, db)
    if not payload.use_browser:
        raise HTTPException(
            status_code=400,
            detail="请设置 use_browser=true，或改用手动粘贴/上传接口",
        )
    try:
        transcript = await notebooklm_service.fetch_via_browser(payload.notebook_url)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc

    summary = notebooklm_service.extract_summary(transcript or "")
    record = NotebookLMInput(
        project_id=project_id,
        notebook_url=payload.notebook_url,
        raw_transcript=transcript,
        extracted_summary=summary,
        synced_at=datetime.now(timezone.utc),
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)
    return record
