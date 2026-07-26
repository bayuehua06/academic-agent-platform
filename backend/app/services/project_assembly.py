"""项目定稿字段刷新：A/C/D → projects 缓存列；B 不写入 projects。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, ProjectSourceDocument
from app.services.outline_parser import parse_outline_from_raw
from app.services.summarizer import summarizer_service

logger = logging.getLogger(__name__)


def _doc_text_for_assembly(doc: ProjectSourceDocument) -> str:
    """优先 summary_text，否则用 raw_text。"""
    if doc.summary_text and doc.summary_text.strip():
        return doc.summary_text.strip()
    return (doc.raw_text or "").strip()


async def refresh_project_assembled_fields(
    db: AsyncSession,
    project_id: UUID,
    *,
    lock_outline_source_id: Optional[UUID] = None,
) -> Project:
    """
    根据源文档重写 projects 定稿列。

    - A → assessment_summary（合并全部 ASSESSMENT；有 Key 时可 LLM 合并）
    - D → specific_requirements（合并全部 SPECIFIC）
    - C → 仅当传入 lock_outline_source_id 时写入 paper_outline + outline_locked_at
    - B → 不改 projects
    """
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise ValueError(f"项目不存在: {project_id}")

    docs_result = await db.execute(
        select(ProjectSourceDocument)
        .where(ProjectSourceDocument.project_id == project_id)
        .order_by(ProjectSourceDocument.created_at.asc())
    )
    docs = list(docs_result.scalars().all())

    a_parts = [
        _doc_text_for_assembly(d)
        for d in docs
        if d.role == "ASSESSMENT" and _doc_text_for_assembly(d)
    ]
    d_parts = [
        _doc_text_for_assembly(d)
        for d in docs
        if d.role == "SPECIFIC" and _doc_text_for_assembly(d)
    ]

    project.assessment_summary = (
        summarizer_service.merge_assessment_parts(a_parts) if a_parts else None
    )
    project.specific_requirements = "\n\n---\n\n".join(d_parts) if d_parts else None

    if lock_outline_source_id is not None:
        outline_doc = next((d for d in docs if d.id == lock_outline_source_id), None)
        if not outline_doc:
            raise ValueError("大纲源文档不存在")
        if outline_doc.role != "OUTLINE":
            raise ValueError("仅 OUTLINE 角色文档可锁定为论文大纲")

        outline = outline_doc.summary_json
        if not isinstance(outline, list) or not outline:
            outline = parse_outline_from_raw(
                outline_doc.raw_text or "",
                storage_path=outline_doc.storage_path,
                original_filename=outline_doc.original_filename,
            )
            outline_doc.summary_json = outline
            if outline:
                summarizer_service.apply_to_document(outline_doc)
            else:
                outline_doc.status = "FAILED"
                outline_doc.error_message = "未能解析出任何标题"
                raise ValueError("未能从大纲文档解析出标题结构")
        elif outline_doc.status != "SUMMARIZED":
            summarizer_service.apply_to_document(outline_doc)

        if not outline:
            raise ValueError("未能从大纲文档解析出标题结构")

        project.paper_outline = outline
        project.outline_locked_at = datetime.now(timezone.utc)

    project.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(project)
    logger.info(
        "已刷新定稿 project=%s assessment=%s outline_locked=%s specific=%s",
        project_id,
        bool(project.assessment_summary),
        bool(project.outline_locked_at),
        bool(project.specific_requirements),
    )
    return project


def ensure_writing_ready(project: Project) -> None:
    """写作前校验：必须有 A 定稿 + 已锁定 C。失败抛 ValueError。"""
    if not (project.assessment_summary and project.assessment_summary.strip()):
        raise ValueError("缺少 Assessment 定稿（请先上传/粘贴 A 类材料）")
    if not project.paper_outline or not project.outline_locked_at:
        raise ValueError("论文大纲尚未锁定（请上传 C 类大纲并锁定）")
