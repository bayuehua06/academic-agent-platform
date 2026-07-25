"""草稿版本、导出与 Word 逆向导入。"""

from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.db.models import DraftVersion, Project, User
from app.models.schemas import DraftVersionOut
from app.services.pandoc_service import pandoc_service

router = APIRouter(prefix="/drafts", tags=["drafts"])


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


@router.post("/import-docx", response_model=DraftVersionOut, status_code=status.HTTP_201_CREATED)
async def import_docx(
    project_id: UUID = Query(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DraftVersionOut:
    """上传修改后的 Word，转为 Markdown 并创建新版本（MANUAL_IMPORT）。"""
    await _assert_project_owner(project_id, current_user, db)
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="仅支持 .docx 文件")

    content = await file.read()
    saved = pandoc_service.save_upload(content, suffix=".docx")
    markdown = pandoc_service.docx_to_markdown(saved)

    ver_result = await db.execute(
        select(func.coalesce(func.max(DraftVersion.version_number), 0)).where(
            DraftVersion.project_id == project_id
        )
    )
    next_version = int(ver_result.scalar_one()) + 1
    draft = DraftVersion(
        project_id=project_id,
        version_number=next_version,
        content_markdown=markdown,
        apa_references_block=None,
        source_type="MANUAL_IMPORT",
        changelog=f"从 Word 导入: {file.filename}",
    )
    db.add(draft)
    await db.flush()
    await db.refresh(draft)
    return draft


@router.get("/{project_id}", response_model=List[DraftVersionOut])
async def list_drafts(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[DraftVersionOut]:
    """列出项目全部草稿版本（新到旧）。"""
    await _assert_project_owner(project_id, current_user, db)
    result = await db.execute(
        select(DraftVersion)
        .where(DraftVersion.project_id == project_id)
        .order_by(DraftVersion.version_number.desc())
    )
    return list(result.scalars().all())


@router.get("/{project_id}/latest", response_model=DraftVersionOut)
async def latest_draft(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DraftVersionOut:
    """获取最新草稿。"""
    await _assert_project_owner(project_id, current_user, db)
    result = await db.execute(
        select(DraftVersion)
        .where(DraftVersion.project_id == project_id)
        .order_by(DraftVersion.version_number.desc())
        .limit(1)
    )
    draft = result.scalar_one_or_none()
    if not draft:
        raise HTTPException(status_code=404, detail="尚无草稿版本")
    return draft


@router.get("/{project_id}/export")
async def export_draft(
    project_id: UUID,
    format: str = Query("docx", pattern="^(docx|pdf)$"),
    version_id: UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """导出草稿为 Word 或 PDF。"""
    await _assert_project_owner(project_id, current_user, db)
    if version_id:
        result = await db.execute(
            select(DraftVersion).where(
                DraftVersion.id == version_id, DraftVersion.project_id == project_id
            )
        )
    else:
        result = await db.execute(
            select(DraftVersion)
            .where(DraftVersion.project_id == project_id)
            .order_by(DraftVersion.version_number.desc())
            .limit(1)
        )
    draft = result.scalar_one_or_none()
    if not draft:
        raise HTTPException(status_code=404, detail="草稿不存在")

    try:
        path = pandoc_service.markdown_to_document(
            draft.content_markdown,
            draft.apa_references_block,
            fmt=format,  # type: ignore[arg-type]
            filename_stem=f"project_{project_id}_v{draft.version_number}",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    media = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if format == "docx"
        else "application/pdf"
    )
    return FileResponse(path, media_type=media, filename=path.name)
