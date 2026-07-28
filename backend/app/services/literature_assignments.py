"""章节↔文献分配：Attach 下 Writer 真源；一篇可属多章。"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Set
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Literature, LiteratureSectionAssignment, Project
from app.models.schemas import LiteratureOut
from app.services.literature_workflow import extract_outline_headings
from app.services.zotero_service import zotero_for_project


def _binding_mode(project: Project) -> str:
    return (project.zotero_binding_mode or "create").strip().lower() or "create"


def is_attach_mode(project: Project) -> bool:
    return _binding_mode(project) == "attach"


async def load_assignment_map(
    project_id: UUID, db: AsyncSession
) -> Dict[UUID, List[str]]:
    """literature_id → assigned outline_heading 列表（保序去重）。"""
    result = await db.execute(
        select(LiteratureSectionAssignment)
        .where(LiteratureSectionAssignment.project_id == project_id)
        .order_by(LiteratureSectionAssignment.created_at.asc())
    )
    out: Dict[UUID, List[str]] = {}
    for row in result.scalars().all():
        heads = out.setdefault(row.literature_id, [])
        h = (row.outline_heading or "").strip()
        if h and h not in heads:
            heads.append(h)
    return out


async def build_collection_path_map(project: Project) -> Dict[str, str]:
    """
    zotero_subcollection_key → 展示路径。

    根 key → 根名；子集合 key → 「根名 / 子名」。
    """
    root = (project.zotero_collection_id or "").strip()
    if not root:
        return {}
    root_name = (project.title or "").strip() or root
    paths: Dict[str, str] = {root: root_name}
    try:
        svc = zotero_for_project(project)
        if svc.is_configured:
            for child in svc.list_child_collections(root):
                key = (child.get("key") or "").strip()
                name = (child.get("name") or "").strip() or key
                if key:
                    paths[key] = f"{root_name} / {name}"
    except Exception:  # noqa: BLE001
        pass
    return paths


def literature_to_out(
    lit: Literature,
    assigned_headings: Optional[Sequence[str]] = None,
    collection_path: Optional[str] = None,
) -> LiteratureOut:
    """ORM → LiteratureOut，附带分配与路径。"""
    return LiteratureOut(
        id=lit.id,
        project_id=lit.project_id,
        zotero_item_key=lit.zotero_item_key,
        zotero_subcollection_key=lit.zotero_subcollection_key,
        outline_heading=lit.outline_heading,
        source_query=lit.source_query,
        title=lit.title,
        authors=lit.authors,
        year=lit.year,
        doi=lit.doi,
        abstract=lit.abstract,
        landing_url=lit.landing_url,
        evidence_tier=lit.evidence_tier,
        evidence_source=lit.evidence_source,
        evidence_fetched_at=lit.evidence_fetched_at,
        relevance_score=lit.relevance_score,
        selected_for_draft=lit.selected_for_draft,
        confirmed_at=lit.confirmed_at,
        created_at=lit.created_at,
        assigned_headings=list(assigned_headings or []),
        collection_path=collection_path,
    )


async def list_literatures_enriched(
    project: Project, db: AsyncSession, literatures: Optional[Sequence[Literature]] = None
) -> List[LiteratureOut]:
    """列出项目文献并附 assigned_headings / collection_path。"""
    if literatures is None:
        result = await db.execute(
            select(Literature)
            .where(Literature.project_id == project.id)
            .order_by(Literature.relevance_score.desc().nullslast())
        )
        literatures = list(result.scalars().all())
    assign_map = await load_assignment_map(project.id, db)
    path_map = await build_collection_path_map(project)
    root = (project.zotero_collection_id or "").strip()
    root_name = (project.title or "").strip() or root or "（根）"
    out: List[LiteratureOut] = []
    for lit in literatures:
        key = (lit.zotero_subcollection_key or "").strip()
        path = path_map.get(key) if key else None
        if path is None:
            path = root_name if root else None
        out.append(
            literature_to_out(
                lit,
                assigned_headings=assign_map.get(lit.id, []),
                collection_path=path,
            )
        )
    return out


async def get_assignments_view(project: Project, db: AsyncSession) -> Dict[str, Any]:
    """按章聚合 + 未分配统计。"""
    headings = extract_outline_headings(project.paper_outline)
    assign_map = await load_assignment_map(project.id, db)
    result = await db.execute(
        select(Literature.id).where(Literature.project_id == project.id)
    )
    all_ids = list(result.scalars().all())
    by_heading: Dict[str, List[str]] = {h: [] for h in headings}
    assigned_any: Set[UUID] = set()
    for lit_id, heads in assign_map.items():
        assigned_any.add(lit_id)
        for h in heads:
            if h in by_heading:
                by_heading[h].append(str(lit_id))
            else:
                by_heading.setdefault(h, []).append(str(lit_id))
    sections = [
        {"outline_heading": h, "literature_ids": by_heading.get(h, [])}
        for h in headings
    ]
    # 大纲外遗留 heading 也返回
    for h, ids in by_heading.items():
        if h not in headings:
            sections.append({"outline_heading": h, "literature_ids": ids})
    unassigned = sum(1 for i in all_ids if i not in assigned_any)
    return {
        "sections": sections,
        "unassigned_count": unassigned,
        "total_count": len(all_ids),
    }


async def replace_section_assignments(
    project: Project,
    db: AsyncSession,
    outline_heading: str,
    literature_ids: Sequence[UUID],
) -> Dict[str, Any]:
    """整章覆盖该章分配（幂等）。"""
    heading = (outline_heading or "").strip()
    if not heading:
        raise ValueError("outline_heading 不能为空")
    headings = extract_outline_headings(project.paper_outline)
    if heading not in headings:
        raise ValueError(f"大纲中不存在章节: {heading!r}")

    # 去重保序
    seen: Set[UUID] = set()
    unique_ids: List[UUID] = []
    for lid in literature_ids:
        if lid in seen:
            continue
        seen.add(lid)
        unique_ids.append(lid)

    if unique_ids:
        result = await db.execute(
            select(Literature.id).where(
                Literature.project_id == project.id,
                Literature.id.in_(unique_ids),
            )
        )
        found = set(result.scalars().all())
        missing = [str(i) for i in unique_ids if i not in found]
        if missing:
            raise ValueError(f"文献不属于本项目: {', '.join(missing[:5])}")

    await db.execute(
        delete(LiteratureSectionAssignment).where(
            LiteratureSectionAssignment.project_id == project.id,
            LiteratureSectionAssignment.outline_heading == heading,
        )
    )
    for lid in unique_ids:
        db.add(
            LiteratureSectionAssignment(
                project_id=project.id,
                literature_id=lid,
                outline_heading=heading,
            )
        )
    await db.flush()
    return await get_assignments_view(project, db)


def sources_from_literatures_for_writer(
    project: Project,
    literatures: Sequence[Literature],
    assign_map: Dict[UUID, List[str]],
) -> List[Dict[str, Any]]:
    """
    组装 run-agent / Writer 的 existing_sources。

    attach：仅含至少分配到一章的文献，并带 assigned_headings。
    create：selected_for_draft 全局池（无 assigned_headings）。
    """
    if is_attach_mode(project):
        out: List[Dict[str, Any]] = []
        for lit in literatures:
            heads = assign_map.get(lit.id) or []
            if not heads:
                continue
            out.append(
                {
                    "title": lit.title,
                    "authors": lit.authors or [],
                    "year": lit.year or "",
                    "doi": lit.doi or "",
                    "abstract": lit.abstract or "",
                    "landing_url": lit.landing_url or "",
                    "evidence_text": lit.evidence_text or "",
                    "evidence_tier": lit.evidence_tier or "",
                    "evidence_source": lit.evidence_source or "",
                    "evidence_content_key": lit.evidence_content_key or "",
                    "relevance_score": lit.relevance_score or 0.0,
                    "zotero_item_key": lit.zotero_item_key,
                    "assigned_headings": list(heads),
                }
            )
        return out

    return [
        {
            "title": lit.title,
            "authors": lit.authors or [],
            "year": lit.year or "",
            "doi": lit.doi or "",
            "abstract": lit.abstract or "",
            "landing_url": lit.landing_url or "",
            "evidence_text": lit.evidence_text or "",
            "evidence_tier": lit.evidence_tier or "",
            "evidence_source": lit.evidence_source or "",
            "evidence_content_key": lit.evidence_content_key or "",
            "relevance_score": lit.relevance_score or 0.0,
            "zotero_item_key": lit.zotero_item_key,
        }
        for lit in literatures
        if lit.selected_for_draft
    ]


def filter_sources_for_heading(
    sources: Iterable[Dict[str, Any]] | Iterable[Any],
    heading: str,
) -> List[Any]:
    """
    若源带 assigned_headings，则只保留分配到该章的；否则原样返回（create）。
    """
    src_list = list(sources or [])
    if not src_list:
        return []
    has_mode = False
    for s in src_list:
        if isinstance(s, dict) and "assigned_headings" in s:
            has_mode = True
            break
        if hasattr(s, "get") and "assigned_headings" in (s or {}):  # type: ignore[operator]
            has_mode = True
            break
    if not has_mode:
        return src_list
    h = (heading or "").strip()
    out: List[Any] = []
    for s in src_list:
        if isinstance(s, dict):
            heads = s.get("assigned_headings") or []
        else:
            heads = getattr(s, "assigned_headings", None) or []
        if h in heads:
            out.append(s)
    return out
