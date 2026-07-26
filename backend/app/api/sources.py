"""项目源文档（A/B/C/D）API。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.db.models import Project, ProjectSourceDocument, User
from app.models.schemas import (
    NotebookSyncCreate,
    OutlineLockRequest,
    SourceDocumentCreate,
    SourceDocumentOut,
)
from app.services.document_ingest import (
    document_ingest_service,
    validate_role,
    validate_source_type,
)
from app.services.notebooklm import notebooklm_service
from app.services.outline_parser import parse_outline_from_raw
from app.services.project_assembly import refresh_project_assembled_fields
from app.services.summarizer import summarizer_service

router = APIRouter(prefix="/projects", tags=["sources"])


async def _get_owned_project(
    project_id: UUID, user: User, db: AsyncSession
) -> Project:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


async def _get_owned_source(
    project_id: UUID, source_id: UUID, user: User, db: AsyncSession
) -> ProjectSourceDocument:
    await _get_owned_project(project_id, user, db)
    result = await db.execute(
        select(ProjectSourceDocument).where(
            ProjectSourceDocument.id == source_id,
            ProjectSourceDocument.project_id == project_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="源文档不存在")
    return doc


def _apply_parse_and_summarize(doc: ProjectSourceDocument) -> None:
    """解析正文/大纲，再生成摘要（无 API Key 时直存原文）。"""
    raw = doc.raw_text or ""
    doc.error_message = None
    doc.updated_at = datetime.now(timezone.utc)

    if doc.role == "OUTLINE":
        outline = parse_outline_from_raw(
            raw,
            storage_path=doc.storage_path,
            original_filename=doc.original_filename,
        )
        doc.summary_json = outline
        if not outline:
            doc.status = "FAILED"
            doc.error_message = "未能解析出任何标题"
            doc.summary_text = None
            return
        doc.status = "PARSED"
        summarizer_service.apply_to_document(doc)
        return

    doc.summary_json = None
    doc.status = "PARSED"
    summarizer_service.apply_to_document(doc)


@router.get("/{project_id}/sources", response_model=List[SourceDocumentOut])
async def list_sources(
    project_id: UUID,
    role: Optional[str] = Query(None, description="按 role 过滤"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[SourceDocumentOut]:
    """列出项目源文档，可按 role 过滤。"""
    await _get_owned_project(project_id, current_user, db)
    stmt = (
        select(ProjectSourceDocument)
        .where(ProjectSourceDocument.project_id == project_id)
        .order_by(ProjectSourceDocument.created_at.desc())
    )
    if role:
        try:
            stmt = stmt.where(ProjectSourceDocument.role == validate_role(role))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post(
    "/{project_id}/sources",
    response_model=SourceDocumentOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_source_paste(
    project_id: UUID,
    payload: SourceDocumentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SourceDocumentOut:
    """粘贴创建源文档（source_type 默认 PASTE）。"""
    await _get_owned_project(project_id, current_user, db)
    try:
        role = validate_role(payload.role)
        source_type = validate_source_type(payload.source_type or "PASTE")
        if source_type != "PASTE":
            raise ValueError("JSON 创建仅支持 source_type=PASTE；上传请用 /sources/upload")
        ingested = document_ingest_service.ingest_paste(
            payload.raw_text or "",
            title=payload.title,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    doc = ProjectSourceDocument(
        project_id=project_id,
        role=role,
        source_type=source_type,
        title=ingested.title,
        notebook_url=payload.notebook_url,
        raw_text=ingested.raw_text,
        status="PENDING",
    )
    _apply_parse_and_summarize(doc)
    db.add(doc)
    await db.flush()

    if role in {"ASSESSMENT", "SPECIFIC"}:
        await refresh_project_assembled_fields(db, project_id)

    await db.refresh(doc)
    return doc


@router.post(
    "/{project_id}/sources/upload",
    response_model=SourceDocumentOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_source(
    project_id: UUID,
    role: str = Form(...),
    title: Optional[str] = Form(None),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SourceDocumentOut:
    """上传 Word/PDF/Markdown/文本作为源文档。"""
    await _get_owned_project(project_id, current_user, db)
    try:
        role_value = validate_role(role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    content = await file.read()
    try:
        ingested = document_ingest_service.ingest_bytes(
            content,
            filename=file.filename or "upload.bin",
            content_type=file.content_type,
            project_id=project_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    doc = ProjectSourceDocument(
        project_id=project_id,
        role=role_value,
        source_type="UPLOAD",
        title=title or ingested.title,
        original_filename=ingested.original_filename,
        content_type=ingested.content_type,
        storage_path=ingested.storage_path,
        raw_text=ingested.raw_text,
        status="PENDING",
    )
    _apply_parse_and_summarize(doc)
    db.add(doc)
    await db.flush()

    if role_value in {"ASSESSMENT", "SPECIFIC"}:
        await refresh_project_assembled_fields(db, project_id)

    await db.refresh(doc)
    return doc


@router.post(
    "/{project_id}/sources/notebook-sync",
    response_model=SourceDocumentOut,
    status_code=status.HTTP_201_CREATED,
)
async def sync_notebook_source(
    project_id: UUID,
    payload: NotebookSyncCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SourceDocumentOut:
    """抓取 NotebookLM 全文，创建 BACKGROUND + NOTEBOOKLM 源文档（不改 projects 定稿列）。"""
    await _get_owned_project(project_id, current_user, db)
    if not payload.use_browser:
        raise HTTPException(status_code=400, detail="当前仅支持 use_browser=true")

    try:
        transcript = await notebooklm_service.fetch_via_browser(payload.notebook_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502, detail=f"NotebookLM 抓取失败: {exc}"
        ) from exc

    text = (transcript or "").strip()
    if not text:
        raise HTTPException(status_code=502, detail="抓取结果为空")

    doc = ProjectSourceDocument(
        project_id=project_id,
        role="BACKGROUND",
        source_type="NOTEBOOKLM",
        title="NotebookLM",
        notebook_url=payload.notebook_url,
        raw_text=text,
        status="PENDING",
    )
    _apply_parse_and_summarize(doc)
    db.add(doc)
    await db.flush()
    await db.refresh(doc)
    return doc


@router.delete(
    "/{project_id}/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_source(
    project_id: UUID,
    source_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """删除源文档；若为 A/D 则刷新定稿。"""
    doc = await _get_owned_source(project_id, source_id, current_user, db)
    role = doc.role
    await db.delete(doc)
    await db.flush()
    if role in {"ASSESSMENT", "SPECIFIC"}:
        await refresh_project_assembled_fields(db, project_id)


@router.post(
    "/{project_id}/sources/{source_id}/reparse",
    response_model=SourceDocumentOut,
)
async def reparse_source(
    project_id: UUID,
    source_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SourceDocumentOut:
    """重新解析已有源文档（从 storage_path 或 raw_text），并重新摘要。"""
    doc = await _get_owned_source(project_id, source_id, current_user, db)

    try:
        if doc.storage_path and doc.source_type == "UPLOAD":
            from pathlib import Path

            path = Path(doc.storage_path)
            if path.exists():
                doc.raw_text = document_ingest_service.extract_text_from_file(
                    path,
                    filename=doc.original_filename,
                    content_type=doc.content_type,
                )
        if not (doc.raw_text or "").strip():
            raise ValueError("无可解析文本")
        _apply_parse_and_summarize(doc)
    except ValueError as exc:
        doc.status = "FAILED"
        doc.error_message = str(exc)
        await db.flush()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await db.flush()
    if doc.role in {"ASSESSMENT", "SPECIFIC"}:
        await refresh_project_assembled_fields(db, project_id)
    await db.refresh(doc)
    return doc


@router.post(
    "/{project_id}/sources/{source_id}/summarize",
    response_model=SourceDocumentOut,
)
async def summarize_source(
    project_id: UUID,
    source_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SourceDocumentOut:
    """
    对已有源文档重新摘要。

    有 OPENAI_API_KEY 时调用 gpt-4o-mini；否则直存 raw_text / 大纲文本为 summary。
    """
    doc = await _get_owned_source(project_id, source_id, current_user, db)
    if doc.role == "OUTLINE" and not (
        isinstance(doc.summary_json, list) and doc.summary_json
    ):
        _apply_parse_and_summarize(doc)
    else:
        if not (doc.raw_text or "").strip() and doc.role != "OUTLINE":
            raise HTTPException(status_code=400, detail="无可摘要文本")
        if doc.status == "FAILED":
            raise HTTPException(status_code=400, detail="文档解析失败，请先 reparse")
        summarizer_service.apply_to_document(doc)

    await db.flush()
    if doc.role in {"ASSESSMENT", "SPECIFIC"}:
        await refresh_project_assembled_fields(db, project_id)
    await db.refresh(doc)
    return doc


@router.post("/{project_id}/outline/lock", response_model=SourceDocumentOut)
async def lock_outline(
    project_id: UUID,
    payload: OutlineLockRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SourceDocumentOut:
    """
    锁定论文大纲到 projects.paper_outline。

    未传 source_id 时使用最新一条 OUTLINE 文档。
    """
    await _get_owned_project(project_id, current_user, db)

    source_id = payload.source_id
    if source_id is None:
        result = await db.execute(
            select(ProjectSourceDocument)
            .where(
                ProjectSourceDocument.project_id == project_id,
                ProjectSourceDocument.role == "OUTLINE",
            )
            .order_by(ProjectSourceDocument.created_at.desc())
            .limit(1)
        )
        doc = result.scalar_one_or_none()
        if not doc:
            raise HTTPException(status_code=400, detail="尚无 OUTLINE 源文档可锁定")
        source_id = doc.id
    else:
        doc = await _get_owned_source(project_id, source_id, current_user, db)
        if doc.role != "OUTLINE":
            raise HTTPException(status_code=400, detail="指定文档不是 OUTLINE 角色")

    # 确保解析最新
    _apply_parse_and_summarize(doc)
    await db.flush()

    try:
        await refresh_project_assembled_fields(
            db, project_id, lock_outline_source_id=source_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await db.refresh(doc)
    return doc
