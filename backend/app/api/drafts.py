"""草稿版本、精修工作区、导出与 Word 导入。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.db.models import (
    DraftVersion,
    DraftWorking,
    Literature,
    Project,
    SectionDirective,
    User,
)
from app.models.schemas import (
    AcceptSectionRequest,
    DraftVersionOut,
    DraftWorkingOut,
    PolishSectionPreview,
    PolishSectionRequest,
    WorkingFactsUpdate,
)
from app.services.apa_docx import sanitize_export_stem
from app.services.draft_polish import (
    build_pending_directive,
    build_upstream_summaries,
    headings_after,
    match_outline_key_points,
    outline_seeds_map,
    polish_section_markdown,
)
from app.services.draft_sections import (
    diff_sections,
    find_section,
    highlight_line_diff,
    replace_section_in_markdown,
    split_markdown_sections,
)
from app.services.draft_versioning import (
    apply_section_overrides,
    format_display_label,
    labels_from_draft,
    next_minor_for_major,
    next_version_number,
)
from app.services.pandoc_service import pandoc_service
from app.services.references_rebuild import rebuild_apa_references_from_citations

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


def _draft_out(
    draft: DraftVersion,
    *,
    citation_warnings: Optional[List[str]] = None,
    directives_persisted: Optional[int] = None,
    references_matched: Optional[int] = None,
) -> DraftVersionOut:
    major, minor, label = labels_from_draft(draft)
    return DraftVersionOut(
        id=draft.id,
        project_id=draft.project_id,
        version_number=draft.version_number,
        major=major,
        minor=minor,
        display_label=label,
        parent_version_id=draft.parent_version_id,
        base_version_id=draft.base_version_id,
        content_markdown=draft.content_markdown,
        apa_references_block=draft.apa_references_block,
        source_type=draft.source_type,
        changelog=draft.changelog,
        created_at=draft.created_at,
        citation_warnings=citation_warnings,
        directives_persisted=directives_persisted,
        references_matched=references_matched,
    )


async def _get_active_working(
    db: AsyncSession, project_id: UUID
) -> Optional[DraftWorking]:
    result = await db.execute(
        select(DraftWorking).where(
            DraftWorking.project_id == project_id,
            DraftWorking.status == "ACTIVE",
        )
    )
    return result.scalar_one_or_none()


async def _working_out(db: AsyncSession, working: DraftWorking) -> DraftWorkingOut:
    base_label = None
    base_md = ""
    base = await db.get(DraftVersion, working.base_version_id)
    if base:
        _, _, base_label = labels_from_draft(base)
        base_md = base.content_markdown or ""

    overrides = working.section_overrides or {}
    polished_headings = list(overrides.keys())
    composed = apply_section_overrides(working.content_markdown, overrides)
    diffs = diff_sections(base_md, composed, polished_headings=polished_headings)
    sections_payload = [
        {
            "heading": d.heading,
            "level": d.level,
            "status": d.status,
            "similarity": d.similarity,
            "has_locked_blocks": d.has_locked_blocks,
            "locked_count": d.locked_count,
            "polished": d.polished,
        }
        for d in diffs
        if d.status != "removed"
    ]

    project = await db.get(Project, working.project_id)
    seeds = outline_seeds_map(project.paper_outline if project else None)

    return DraftWorkingOut(
        id=working.id,
        project_id=working.project_id,
        base_version_id=working.base_version_id,
        base_display_label=base_label,
        content_markdown=composed,
        section_overrides=working.section_overrides,
        pending_directives=working.pending_directives,
        working_facts=working.working_facts,
        stale_headings=list(working.stale_headings or []),
        status=working.status,
        source_filename=working.source_filename,
        created_at=working.created_at,
        updated_at=working.updated_at,
        sections=sections_payload,
        outline_seeds=seeds or None,
    )


async def _discard_active_working(db: AsyncSession, project_id: UUID) -> None:
    existing = await _get_active_working(db, project_id)
    if existing:
        existing.status = "DISCARDED"
        existing.updated_at = datetime.now(timezone.utc)


async def _open_working(
    db: AsyncSession,
    project: Project,
    base: DraftVersion,
    *,
    content_markdown: str,
    source_filename: Optional[str],
) -> DraftWorking:
    await _discard_active_working(db, project.id)
    seed_facts = (project.confirmed_facts or "").strip() or None
    working = DraftWorking(
        project_id=project.id,
        base_version_id=base.id,
        content_markdown=content_markdown,
        section_overrides={},
        pending_directives=[],
        working_facts=seed_facts,
        stale_headings=[],
        status="ACTIVE",
        source_filename=source_filename,
    )
    db.add(working)
    project.status = "HAS_DRAFT"
    await db.flush()
    await db.refresh(working)
    return working


async def _persist_pending_directives(
    db: AsyncSession,
    *,
    project: Project,
    working: DraftWorking,
    draft: DraftVersion,
) -> int:
    """将工作区 pending_directives 落库为 SectionDirective。"""
    pending = list(working.pending_directives or [])
    count = 0
    for item in pending:
        if not isinstance(item, dict):
            continue
        heading = (item.get("outline_heading") or "").strip()
        text = (item.get("directive_text") or "").strip()
        if not heading or not text:
            continue
        instruction = (item.get("instruction") or "").strip()
        if instruction.startswith("[manual edit]"):
            continue
        db.add(
            SectionDirective(
                project_id=project.id,
                outline_heading=heading,
                directive_text=text,
                instruction=instruction or None,
                source_working_id=working.id,
                confirmed_version_id=draft.id,
                active=True,
            )
        )
        count += 1
    return count


@router.post("/import-docx", response_model=DraftWorkingOut, status_code=status.HTTP_201_CREATED)
async def import_docx(
    project_id: UUID = Query(...),
    base_version_id: UUID = Query(..., description="基于哪个已确认版本开启精修工作区"),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DraftWorkingOut:
    """
    上传修改后的 Word → 进入 ACTIVE 精修工作区（不立即产生版本号）。

    需指定 base_version_id；确认工作区后才生成 major.minor（如 9.1）。
    """
    project = await _assert_project_owner(project_id, current_user, db)
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="仅支持 .docx 文件")

    base = await db.get(DraftVersion, base_version_id)
    if not base or base.project_id != project_id:
        raise HTTPException(status_code=400, detail="base_version_id 无效")

    content = await file.read()
    saved = pandoc_service.save_upload(content, suffix=".docx")
    markdown = pandoc_service.docx_to_markdown(saved)

    working = await _open_working(
        db,
        project,
        base,
        content_markdown=markdown,
        source_filename=file.filename,
    )
    return await _working_out(db, working)


@router.post("/{project_id}/working/start", response_model=DraftWorkingOut, status_code=status.HTTP_201_CREATED)
async def start_working_from_version(
    project_id: UUID,
    base_version_id: UUID = Query(..., description="基于该已确认版本复制正文开启精修（无需上传）"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DraftWorkingOut:
    """
    不上传 Word：以某确认版本正文为工作区起点，直接做分节精修。

    有活动工作区时会被丢弃并替换。
    """
    project = await _assert_project_owner(project_id, current_user, db)
    base = await db.get(DraftVersion, base_version_id)
    if not base or base.project_id != project_id:
        raise HTTPException(status_code=400, detail="base_version_id 无效")

    # 工作区正文 = 定稿正文；References 块仍挂在版本上，确认时 P3 再重建
    body = (base.content_markdown or "").strip()
    if base.apa_references_block and base.apa_references_block.strip():
        # 若正文尚无 References 标题，附上便于分节展示（锁定不精修）
        from app.services.pandoc_service import re_has_references_heading

        if not re_has_references_heading(body):
            body = f"{body}\n\n## References\n\n{base.apa_references_block.strip()}\n"

    working = await _open_working(
        db,
        project,
        base,
        content_markdown=body if body.endswith("\n") else body + "\n",
        source_filename=None,
    )
    return await _working_out(db, working)


async def _confirm_working_inner(
    db: AsyncSession, project: Project, working: DraftWorking
) -> tuple[DraftVersion, List[str], int, int]:
    base = await db.get(DraftVersion, working.base_version_id)
    if not base:
        raise HTTPException(status_code=400, detail="工作区 base 版本已不存在")

    major, _, base_label = labels_from_draft(base)
    next_minor = await next_minor_for_major(db, project.id, major)
    if base.major is None:
        base.major = major
        base.minor = base.minor or 0

    body = apply_section_overrides(working.content_markdown, working.section_overrides)

    lit_result = await db.execute(
        select(Literature).where(Literature.project_id == project.id)
    )
    lits = list(lit_result.scalars().all())
    sources = [
        {
            "title": x.title,
            "authors": x.authors or [],
            "year": x.year,
            "doi": x.doi,
        }
        for x in lits
    ]
    body_clean, refs_block, unmatched, matched_n = rebuild_apa_references_from_citations(
        body, sources
    )
    # 无文内引用时保留 base 的 References（避免空库误清空）
    if matched_n == 0 and not unmatched:
        refs_block = base.apa_references_block or ""
        body_clean = body

    ver_no = await next_version_number(db, project.id)
    label = format_display_label(major, next_minor)
    warn_bit = f"；未匹配引用 {len(unmatched)} 条" if unmatched else ""
    draft = DraftVersion(
        project_id=project.id,
        version_number=ver_no,
        major=major,
        minor=next_minor,
        parent_version_id=base.id,
        base_version_id=base.id,
        content_markdown=body_clean,
        apa_references_block=refs_block or None,
        source_type="POLISH_CONFIRM",
        changelog=(
            f"确认精修工作区 → v{label}（基于 v{base_label}；"
            f"上传文件={working.source_filename or '-'}；"
            f"References 匹配 {matched_n}{warn_bit}）"
        ),
    )
    db.add(draft)
    await db.flush()
    await db.refresh(draft)

    directives_n = await _persist_pending_directives(
        db, project=project, working=working, draft=draft
    )

    if working.working_facts and working.working_facts.strip():
        project.confirmed_facts = working.working_facts.strip()

    working.status = "CONFIRMED"
    working.updated_at = datetime.now(timezone.utc)
    project.status = "HAS_DRAFT"
    await db.flush()
    await db.refresh(draft)
    return draft, unmatched, directives_n, matched_n


@router.get("/{project_id}/working", response_model=Optional[DraftWorkingOut])
async def get_draft_working(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Optional[DraftWorkingOut]:
    """获取当前 ACTIVE 精修工作区；无则 null。"""
    await _assert_project_owner(project_id, current_user, db)
    working = await _get_active_working(db, project_id)
    if not working:
        return None
    return await _working_out(db, working)


@router.delete("/{project_id}/working", status_code=status.HTTP_204_NO_CONTENT)
async def discard_draft_working(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """丢弃 ACTIVE 工作区。"""
    await _assert_project_owner(project_id, current_user, db)
    working = await _get_active_working(db, project_id)
    if not working:
        raise HTTPException(status_code=404, detail="无活动中的精修工作区")
    working.status = "DISCARDED"
    working.updated_at = datetime.now(timezone.utc)
    await db.flush()


@router.post("/{project_id}/working/confirm", response_model=DraftVersionOut)
async def confirm_draft_working(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DraftVersionOut:
    """确认工作区 → 小版本 + References 重建 + directives/Facts 落库。"""
    project = await _assert_project_owner(project_id, current_user, db)
    working = await _get_active_working(db, project_id)
    if not working:
        raise HTTPException(status_code=404, detail="无活动中的精修工作区")
    draft, warnings, dir_n, matched_n = await _confirm_working_inner(db, project, working)
    return _draft_out(
        draft,
        citation_warnings=warnings or None,
        directives_persisted=dir_n,
        references_matched=matched_n,
    )


@router.get("/{project_id}/working/section-diff")
async def get_section_line_diff(
    project_id: UUID,
    heading: str = Query(..., min_length=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """P1：单节相对 base 的行级 diff。"""
    await _assert_project_owner(project_id, current_user, db)
    working = await _get_active_working(db, project_id)
    if not working:
        raise HTTPException(status_code=404, detail="无活动中的精修工作区")
    base = await db.get(DraftVersion, working.base_version_id)
    if not base:
        raise HTTPException(status_code=400, detail="base 版本不存在")

    composed = apply_section_overrides(working.content_markdown, working.section_overrides)
    base_sec = find_section(split_markdown_sections(base.content_markdown or ""), heading)
    work_sec = find_section(split_markdown_sections(composed), heading)
    if not work_sec and not base_sec:
        raise HTTPException(status_code=404, detail=f"找不到章节: {heading}")

    rows = highlight_line_diff(
        base_sec.body if base_sec else "",
        work_sec.body if work_sec else "",
    )
    project = await db.get(Project, project_id)
    outline_kp = match_outline_key_points(
        project.paper_outline if project else None,
        (work_sec or base_sec).heading,  # type: ignore[union-attr]
    )
    return {
        "heading": (work_sec or base_sec).heading,  # type: ignore[union-attr]
        "has_locked_blocks": bool(work_sec and work_sec.has_locked_blocks),
        "lines": rows,
        "working_markdown": work_sec.full_markdown if work_sec else "",
        "base_markdown": base_sec.full_markdown if base_sec else "",
        "outline_key_points": outline_kp,
    }


@router.post("/{project_id}/working/polish-section", response_model=PolishSectionPreview)
async def polish_working_section(
    project_id: UUID,
    payload: PolishSectionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PolishSectionPreview:
    """对单节生成精修预览（不落盘）；支持多轮 base_markdown。"""
    project = await _assert_project_owner(project_id, current_user, db)
    working = await _get_active_working(db, project_id)
    if not working:
        raise HTTPException(status_code=404, detail="无活动中的精修工作区")

    composed = apply_section_overrides(working.content_markdown, working.section_overrides)
    if payload.section_markdown and payload.section_markdown.strip():
        try:
            composed = replace_section_in_markdown(
                composed, payload.heading, payload.section_markdown.strip()
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 文献：可选勾选，否则项目全部已确认
    lit_q = select(Literature).where(Literature.project_id == project_id)
    if payload.literature_ids:
        lit_q = lit_q.where(Literature.id.in_(payload.literature_ids))
    lit_result = await db.execute(lit_q)
    lits = list(lit_result.scalars().all())
    sources = [
        {
            "title": x.title,
            "authors": x.authors or [],
            "year": x.year,
            "doi": x.doi,
        }
        for x in lits
    ]

    outline_kp = match_outline_key_points(project.paper_outline, payload.heading)
    upstream = build_upstream_summaries(composed, payload.heading)

    # 已落库的章节指令（确认后）一并注入
    dir_result = await db.execute(
        select(SectionDirective).where(
            SectionDirective.project_id == project_id,
            SectionDirective.active.is_(True),
        )
    )
    persisted_bits = []
    for d in dir_result.scalars().all():
        hl = d.outline_heading.strip().lower()
        target = payload.heading.strip().lower()
        if hl == target or target in hl or hl in target:
            persisted_bits.append(f"- {d.directive_text.strip()}")
    facts = (working.working_facts or project.confirmed_facts or "").strip()

    try:
        result = polish_section_markdown(
            full_markdown=composed,
            heading=payload.heading,
            instruction=payload.instruction,
            sources=sources,
            base_markdown=payload.base_markdown,
            prior_instructions=payload.prior_instructions,
            outline_key_points=outline_kp,
            working_facts=facts,
            upstream_summaries=upstream,
            section_directives="\n".join(persisted_bits),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 预览相对「本次输入底稿」的 diff（多轮时相对 base_markdown）
    if payload.base_markdown and payload.base_markdown.strip():
        before_body = ""
        before_sec = find_section(
            split_markdown_sections(payload.base_markdown.strip()), payload.heading
        )
        if before_sec:
            before_body = before_sec.body
        else:
            lines = payload.base_markdown.strip().splitlines()
            before_body = "\n".join(lines[1:]).strip() if lines else ""
    else:
        work_sec = find_section(split_markdown_sections(composed), payload.heading)
        before_body = work_sec.body if work_sec else ""

    preview_sec = find_section(
        split_markdown_sections(result["preview_markdown"]), payload.heading
    )
    line_diff = highlight_line_diff(
        before_body,
        preview_sec.body if preview_sec else result["preview_markdown"],
    )

    return PolishSectionPreview(
        heading=result["heading"],
        preview_markdown=result["preview_markdown"],
        mode=result["mode"],
        model=result.get("model"),
        locked_count=int(result.get("locked_count") or 0),
        openai_configured=bool(result.get("openai_configured")),
        error=result.get("error"),
        line_diff=line_diff,
    )


@router.patch("/{project_id}/working/facts", response_model=DraftWorkingOut)
async def update_working_facts(
    project_id: UUID,
    payload: WorkingFactsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DraftWorkingOut:
    """更新 Working Facts（跨节硬约束文本）。"""
    await _assert_project_owner(project_id, current_user, db)
    working = await _get_active_working(db, project_id)
    if not working:
        raise HTTPException(status_code=404, detail="无活动中的精修工作区")
    working.working_facts = payload.working_facts.strip() or None
    working.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(working)
    return await _working_out(db, working)


@router.post("/{project_id}/working/accept-section", response_model=DraftWorkingOut)
async def accept_working_section(
    project_id: UUID,
    payload: AcceptSectionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DraftWorkingOut:
    """采纳精修预览 → 写入正文 + overrides + 暂存 directive；标记下游 stale。"""
    await _assert_project_owner(project_id, current_user, db)
    working = await _get_active_working(db, project_id)
    if not working:
        raise HTTPException(status_code=404, detail="无活动中的精修工作区")

    try:
        new_md = replace_section_in_markdown(
            working.content_markdown,
            payload.heading,
            payload.preview_markdown,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    overrides = dict(working.section_overrides or {})
    sec = find_section(split_markdown_sections(payload.preview_markdown), payload.heading)
    overrides[payload.heading] = (
        sec.full_markdown if sec else payload.preview_markdown.strip() + "\n"
    )

    pending = list(working.pending_directives or [])
    pending.append(build_pending_directive(payload.heading, payload.instruction))

    # 下游建议再精修；本节从 stale 中移除
    composed_after = apply_section_overrides(new_md, overrides)
    downstream = headings_after(composed_after, payload.heading)
    stale = [h for h in (working.stale_headings or []) if h.lower() != payload.heading.lower()]
    for h in downstream:
        if not any(s.lower() == h.lower() for s in stale):
            stale.append(h)

    working.content_markdown = new_md
    working.section_overrides = overrides
    working.pending_directives = pending
    working.stale_headings = stale
    working.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(working)
    return await _working_out(db, working)


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
    return [_draft_out(d) for d in result.scalars().all()]


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
    return _draft_out(draft)


@router.get("/{project_id}/export")
async def export_draft(
    project_id: UUID,
    format: str = Query("docx", pattern="^(docx|pdf)$"),
    version_id: UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """导出草稿为 Word 或 PDF。"""
    project = await _assert_project_owner(project_id, current_user, db)
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

    _, _, label = labels_from_draft(draft)
    # sanitize_export_stem 第二参历史为 int；改为接受展示标签
    stem = sanitize_export_stem(project.title, label)

    try:
        path = pandoc_service.markdown_to_document(
            draft.content_markdown,
            draft.apa_references_block,
            fmt=format,  # type: ignore[arg-type]
            filename_stem=stem,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    media = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if format == "docx"
        else "application/pdf"
    )
    download_name = path.name
    content_disposition = (
        f'attachment; filename="{download_name}"; '
        f"filename*=UTF-8''{quote(download_name)}"
    )
    return FileResponse(
        path,
        media_type=media,
        filename=download_name,
        headers={"Content-Disposition": content_disposition},
    )
