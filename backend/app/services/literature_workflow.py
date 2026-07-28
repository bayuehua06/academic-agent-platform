"""文献工作流编排：Zotero 结构对齐、绑定与确认入库。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import Literature, LiteratureSectionAssignment, Project
from app.services.zotero_service import ZoteroService, zotero_for_project, zotero_service  # noqa: F401

logger = logging.getLogger(__name__)
settings = get_settings()


def normalize_doi(doi: Optional[str]) -> str:
    """规范化 DOI 便于比对。"""
    if not doi:
        return ""
    text = str(doi).strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    return text.strip()


def normalize_title(title: Optional[str]) -> str:
    """规范化标题便于比对。"""
    if not title:
        return ""
    return " ".join(str(title).lower().split())


def dedupe_candidates(candidates: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    跨库候选去重：优先 DOI，其次规范化标题；保留首次出现（按 provider 顺序）。
    """
    seen_doi: set[str] = set()
    seen_title: set[str] = set()
    out: List[Dict[str, Any]] = []
    for raw in candidates:
        item = dict(raw)
        doi = normalize_doi(item.get("doi"))
        title = normalize_title(item.get("title"))
        if doi and doi in seen_doi:
            continue
        if title and title in seen_title:
            continue
        if doi:
            seen_doi.add(doi)
        if title:
            seen_title.add(title)
        out.append(item)
    return out


def annotate_candidates_against_library(
    candidates: Sequence[Dict[str, Any]],
    existing: Sequence[Any],
) -> List[Dict[str, Any]]:
    """
    为检索候选标注是否已在项目 Collection / 本地镜像中。

    existing 可为 Literature ORM 或含 doi/title/outline_heading/zotero_item_key 的 dict。
    匹配优先 DOI，其次规范化标题。
    """
    by_doi: Dict[str, Any] = {}
    by_title: Dict[str, Any] = {}
    for lit in existing:
        if isinstance(lit, dict):
            doi = normalize_doi(lit.get("doi"))
            title = normalize_title(lit.get("title"))
            heading = lit.get("outline_heading")
            key = lit.get("zotero_item_key")
        else:
            doi = normalize_doi(getattr(lit, "doi", None))
            title = normalize_title(getattr(lit, "title", None))
            heading = getattr(lit, "outline_heading", None)
            key = getattr(lit, "zotero_item_key", None)
        info = {
            "outline_heading": heading,
            "zotero_item_key": key,
        }
        if doi and doi not in by_doi:
            by_doi[doi] = info
        if title and title not in by_title:
            by_title[title] = info

    annotated: List[Dict[str, Any]] = []
    for raw in candidates:
        item = dict(raw)
        match = None
        doi = normalize_doi(item.get("doi"))
        if doi and doi in by_doi:
            match = by_doi[doi]
        else:
            title = normalize_title(item.get("title"))
            if title and title in by_title:
                match = by_title[title]
        if match:
            item["already_exists"] = True
            item["existing_outline_heading"] = match.get("outline_heading")
            item["existing_zotero_item_key"] = match.get("zotero_item_key")
        else:
            item["already_exists"] = False
            item["existing_outline_heading"] = None
            item["existing_zotero_item_key"] = None
        annotated.append(item)
    return annotated


def extract_outline_headings(paper_outline: Any) -> List[str]:
    """从锁定大纲提取章节标题（去重保序）。"""
    if not isinstance(paper_outline, list):
        return []
    seen: set[str] = set()
    headings: List[str] = []
    for item in paper_outline:
        if not isinstance(item, dict):
            continue
        h = (item.get("heading") or "").strip()
        if not h or h in seen:
            continue
        seen.add(h)
        headings.append(h)
    return headings


def _binding_mode(project: Project) -> str:
    return (project.zotero_binding_mode or "create").strip().lower() or "create"


def _ensure_default_library_fields(project: Project) -> None:
    """create 路径：补齐项目级 library 字段为 .env 默认。"""
    if not (project.zotero_library_type or "").strip():
        project.zotero_library_type = (settings.zotero_library_type or "user").strip() or "user"
    if not (project.zotero_library_id or "").strip():
        project.zotero_library_id = (settings.zotero_library_id or "").strip() or None


def _resolve_target_collection(
    service: ZoteroService,
    project: Project,
    target_collection_key: str,
) -> str:
    """校验 target 为绑定根或其直接子集合。"""
    root = (project.zotero_collection_id or "").strip()
    target = (target_collection_key or "").strip()
    if not root:
        raise ValueError("请先绑定 Zotero Collection")
    if not target:
        raise ValueError("attach 模式必须指定 target_collection_key")
    allowed = {root}
    for child in service.list_child_collections(root):
        key = (child.get("key") or "").strip()
        if key:
            allowed.add(key)
    if target not in allowed:
        raise ValueError("target_collection_key 必须是绑定根或其直接子集合")
    return target


async def ensure_zotero_structure(
    project: Project,
    db: AsyncSession,
    zot: Optional[ZoteroService] = None,
) -> Dict[str, Any]:
    """
    创建/对齐项目顶层 Collection 与章节 Subcollection。

    仅 create 模式；写回 projects.zotero_collection_id。
    """
    if _binding_mode(project) == "attach":
        raise ValueError("attach 模式不可调用 ensure-structure；请更换绑定或使用入库目标下拉")

    if not project.zotero_binding_mode:
        project.zotero_binding_mode = "create"
    _ensure_default_library_fields(project)

    service = zot or zotero_for_project(project)
    if not service.is_configured:
        raise RuntimeError("Zotero 未配置")

    headings = extract_outline_headings(project.paper_outline)
    if not headings:
        raise ValueError("请先锁定论文大纲（paper_outline），再创建 Zotero 章节结构")

    root_key, sub_map = service.ensure_project_structure(
        project_title=project.title,
        chapter_headings=headings,
        existing_root_key=project.zotero_collection_id,
    )
    project.zotero_collection_id = root_key
    await db.flush()
    return {
        "zotero_collection_id": root_key,
        "zotero_binding_mode": project.zotero_binding_mode,
        "zotero_library_type": project.zotero_library_type,
        "zotero_library_id": project.zotero_library_id,
        "subcollections": [
            {"outline_heading": h, "zotero_subcollection_key": k} for h, k in sub_map.items()
        ],
    }


async def bind_zotero_collection(
    project: Project,
    db: AsyncSession,
    mode: str,
    collection_key: Optional[str] = None,
    library_type: Optional[str] = None,
    library_id: Optional[str] = None,
    zot: Optional[ZoteroService] = None,
) -> Dict[str, Any]:
    """
    绑定项目文献范围。

    - create：写入 mode + 默认 library，ensure 项目同名 + 章节子集合
    - attach：写入 mode + library + collection，立即全量 sync
    - 仅当确认绑定到**不同**集合时才清空本地文献/章节分配；同集合再绑 = 仅 sync（保留分配）
    """
    mode_n = (mode or "").strip().lower()
    if mode_n not in {"create", "attach"}:
        raise ValueError("mode 必须是 create 或 attach")

    prev_mode = (project.zotero_binding_mode or "").strip().lower() or None
    prev_key = (project.zotero_collection_id or "").strip() or None
    prev_lib_type = (project.zotero_library_type or "").strip() or None
    prev_lib_id = (project.zotero_library_id or "").strip() or None

    if mode_n == "create":
        next_lib_type = (
            (library_type or "").strip()
            or (settings.zotero_library_type or "user").strip()
            or "user"
        )
        next_lib_id = (
            (library_id or "").strip() or (settings.zotero_library_id or "").strip() or None
        )
        # 同为 create 且已有根集合：不先清空，ensure 复用；分配保留
        switching = prev_mode == "attach" or (
            prev_mode == "create" and prev_lib_type and prev_lib_type != next_lib_type
        )
        if switching and prev_key:
            await _clear_project_literatures(project, db)

        project.zotero_binding_mode = "create"
        project.zotero_library_type = next_lib_type
        project.zotero_library_id = next_lib_id
        if switching:
            project.zotero_collection_id = None
        structure = await ensure_zotero_structure(project, db, zot=zot)
        return {
            **structure,
            "synced_count": 0,
            "assignments_cleared": bool(switching and prev_key),
        }

    # attach
    key = (collection_key or "").strip()
    lib_type = (library_type or "").strip()
    lib_id = (library_id or "").strip()
    if not key or not lib_type or not lib_id:
        raise ValueError("attach 需要 collection_key、library_type、library_id")
    if lib_type not in {"user", "group"}:
        raise ValueError("library_type 必须是 user 或 group")

    same_binding = (
        prev_mode == "attach"
        and prev_key == key
        and prev_lib_type == lib_type
        and prev_lib_id == lib_id
    )
    # 真正换到另一个集合/库时才清本地文献与章节分配
    if not same_binding and prev_key:
        await _clear_project_literatures(project, db)

    project.zotero_binding_mode = "attach"
    project.zotero_library_type = lib_type
    project.zotero_library_id = lib_id
    project.zotero_collection_id = key

    service = zot or zotero_for_project(project)
    if not service.is_configured:
        raise RuntimeError("Zotero 未配置")
    if not service.collection_exists(key):
        raise ValueError("无法访问该 Collection（不存在或无权限）")

    synced = await sync_literatures_from_zotero(project, db, zot=service)
    return {
        "zotero_collection_id": key,
        "zotero_binding_mode": "attach",
        "zotero_library_type": lib_type,
        "zotero_library_id": lib_id,
        "subcollections": [],
        "synced_count": len(synced),
        "assignments_cleared": bool(not same_binding and prev_key),
    }


async def _clear_project_literatures(project: Project, db: AsyncSession) -> None:
    """删除项目本地文献（CASCADE 清章节分配）。仅在确认换绑到不同集合时调用。"""
    await db.execute(delete(Literature).where(Literature.project_id == project.id))
    await db.flush()
    # 关系缓存失效，避免后续 sync 读到陈旧集合
    if "literatures" in project.__dict__:
        project.literatures = []


async def _snapshot_assignments_by_item_key(
    project_id, db: AsyncSession, literatures: Sequence[Literature]
) -> Dict[str, List[str]]:
    """zotero_item_key → outline_heading[]，用于 sync 后按 key 恢复分配。"""
    by_lit: Dict[Any, str] = {
        lit.id: lit.zotero_item_key
        for lit in literatures
        if lit.zotero_item_key and lit.id
    }
    if not by_lit:
        return {}
    result = await db.execute(
        select(LiteratureSectionAssignment).where(
            LiteratureSectionAssignment.project_id == project_id,
            LiteratureSectionAssignment.literature_id.in_(list(by_lit.keys())),
        )
    )
    out: Dict[str, List[str]] = {}
    for row in result.scalars().all():
        item_key = by_lit.get(row.literature_id)
        if not item_key:
            continue
        heads = out.setdefault(item_key, [])
        h = (row.outline_heading or "").strip()
        if h and h not in heads:
            heads.append(h)
    return out


async def _restore_assignments_by_item_key(
    project: Project,
    db: AsyncSession,
    literatures: Sequence[Literature],
    snapshot: Dict[str, List[str]],
) -> int:
    """按 zotero_item_key 把章节分配写回（缺的才补；已有不重复）。"""
    if not snapshot:
        return 0
    existing = await db.execute(
        select(LiteratureSectionAssignment).where(
            LiteratureSectionAssignment.project_id == project.id
        )
    )
    have: set[tuple[Any, str]] = {
        (row.literature_id, row.outline_heading) for row in existing.scalars().all()
    }
    restored = 0
    for lit in literatures:
        key = (lit.zotero_item_key or "").strip()
        if not key or key not in snapshot:
            continue
        for heading in snapshot[key]:
            pair = (lit.id, heading)
            if pair in have:
                continue
            db.add(
                LiteratureSectionAssignment(
                    project_id=project.id,
                    literature_id=lit.id,
                    outline_heading=heading,
                )
            )
            have.add(pair)
            restored += 1
    if restored:
        await db.flush()
    return restored


async def sync_literatures_from_zotero(
    project: Project,
    db: AsyncSession,
    zot: Optional[ZoteroService] = None,
) -> List[Literature]:
    """
    以 Zotero 项目 Collection（含直接子集合）为真源，同步到本地 literatures。

    - 远程有、本地无 → 新建（confirmed_at 立即写入）
    - 两边都有（同 zotero_item_key）→ 更新元数据，**保留** literature.id 与章节分配
    - 本地有 key 但远程已无 → 删除本地镜像（其分配随 CASCADE 清除）
    - 同步前按 item_key 快照分配，同步后补回（防止行被重建时丢分配）
    """
    service = zot or zotero_for_project(project)
    if not service.is_configured:
        raise RuntimeError("Zotero 未配置")

    if not project.zotero_collection_id:
        if _binding_mode(project) == "attach":
            raise ValueError("项目尚未绑定 Zotero Collection，请先完成绑定")
        headings = extract_outline_headings(project.paper_outline)
        if headings:
            await ensure_zotero_structure(project, db, zot=service)
        if not project.zotero_collection_id:
            raise ValueError(
                "项目尚无 Zotero Collection。请先绑定（新建或挂接），或完成至少一次文献确认入库"
            )

    remote_items = service.fetch_project_collection_items(project.zotero_collection_id)
    now = datetime.now(timezone.utc)

    # 始终从 DB 拉取，避免 relationship 未加载导致误建重复行、章节分配“丢失”
    lit_result = await db.execute(
        select(Literature).where(Literature.project_id == project.id)
    )
    existing_list = list(lit_result.scalars().all())
    assignment_snapshot = await _snapshot_assignments_by_item_key(
        project.id, db, existing_list
    )

    by_key: Dict[str, Literature] = {}
    for lit in existing_list:
        key = (lit.zotero_item_key or "").strip()
        if not key:
            continue
        # 若历史重复 key，保留最早一条，其余稍后删
        if key not in by_key:
            by_key[key] = lit

    seen_keys: set[str] = set()
    synced: List[Literature] = []

    for meta in remote_items:
        item_key = (meta.get("zotero_item_key") or "").strip()
        if not item_key:
            continue
        seen_keys.add(item_key)
        lit = by_key.get(item_key)
        if lit:
            new_url = meta.get("url")
            new_doi = meta.get("doi")
            url_changed = (lit.landing_url or "") != (new_url or "")
            doi_changed = (lit.doi or "") != (new_doi or "")
            lit.title = meta["title"]
            lit.authors = meta.get("authors") or None
            lit.year = meta.get("year")
            lit.doi = new_doi
            lit.abstract = meta.get("abstract")
            lit.landing_url = new_url
            # URL/DOI 变了则作废全文证据缓存，下次 run-agent 重抓
            if url_changed or doi_changed:
                lit.evidence_text = None
                lit.evidence_content_key = None
                lit.evidence_tier = None
                lit.evidence_source = None
                lit.evidence_fetched_at = None
            # attach 下 outline_heading 不是 Writer 真源；勿用远端子集合名覆盖审计空值以外的用途
            if _binding_mode(project) != "attach":
                lit.outline_heading = meta.get("outline_heading")
            else:
                remote_heading = meta.get("outline_heading")
                if remote_heading and not lit.outline_heading:
                    lit.outline_heading = remote_heading
            lit.zotero_subcollection_key = meta.get("zotero_subcollection_key")
            lit.selected_for_draft = True
            if lit.confirmed_at is None:
                lit.confirmed_at = now
        else:
            lit = Literature(
                project_id=project.id,
                zotero_item_key=item_key,
                zotero_subcollection_key=meta.get("zotero_subcollection_key"),
                outline_heading=meta.get("outline_heading"),
                title=meta["title"],
                authors=meta.get("authors") or None,
                year=meta.get("year"),
                doi=meta.get("doi"),
                abstract=meta.get("abstract"),
                landing_url=meta.get("url"),
                selected_for_draft=True,
                confirmed_at=now,
            )
            db.add(lit)
            by_key[item_key] = lit
        synced.append(lit)

    for lit in existing_list:
        key = (lit.zotero_item_key or "").strip()
        if not key or key not in seen_keys or by_key.get(key) is not lit:
            await db.delete(lit)

    await db.flush()
    for lit in synced:
        await db.refresh(lit)

    restored = await _restore_assignments_by_item_key(
        project, db, synced, assignment_snapshot
    )

    logger.info(
        "Zotero→本地同步完成 project=%s remote=%s kept=%s assignments_restored=%s",
        project.id,
        len(remote_items),
        len(synced),
        restored,
    )
    return synced

async def import_confirmed_items(
    project: Project,
    db: AsyncSession,
    outline_heading: str,
    items: Sequence[Dict[str, Any]],
    source_query: Optional[str] = None,
    zot: Optional[ZoteroService] = None,
    target_collection_key: Optional[str] = None,
) -> List[Literature]:
    """
    将确认的候选写入 Zotero，并镜像到本地 literatures。

    create：写入大纲同名章节子集合（outline_heading 必填且须在大纲中）。
    attach：写入 target_collection_key（根或其直接子集合）；outline_heading 仅作审计。
    """
    if not project.zotero_binding_mode:
        project.zotero_binding_mode = "create"
    mode = _binding_mode(project)
    if mode == "create":
        _ensure_default_library_fields(project)

    service = zot or zotero_for_project(project)
    if not service.is_configured:
        raise RuntimeError("Zotero 未配置")

    heading = (outline_heading or "").strip()
    sub_key: Optional[str] = None

    if mode == "attach":
        if not project.zotero_collection_id:
            raise ValueError("请先绑定 Zotero Collection")
        sub_key = _resolve_target_collection(service, project, target_collection_key or "")
        # 审计：向导当前章可为空
        if not heading:
            heading = ""
    else:
        if not heading:
            raise ValueError("outline_heading 不能为空")
        headings = extract_outline_headings(project.paper_outline)
        if heading not in headings:
            raise ValueError(f"大纲中不存在章节: {heading!r}")

        structure = await ensure_zotero_structure(project, db, zot=service)
        for row in structure["subcollections"]:
            if row["outline_heading"] == heading:
                sub_key = row["zotero_subcollection_key"]
                break
        if not sub_key:
            raise RuntimeError(f"未找到章节子集合: {heading!r}")

    now = datetime.now(timezone.utc)
    created: List[Literature] = []
    for raw in items:
        meta = {
            "title": (raw.get("title") or "Untitled").strip() or "Untitled",
            "authors": raw.get("authors") or [],
            "year": str(raw.get("year") or "") or None,
            "doi": (raw.get("doi") or "").strip() or None,
            "url": (raw.get("url") or "").strip() or None,
            "abstract": raw.get("abstract") or "",
        }
        item_key = service.create_item_from_meta(meta, collection_id=sub_key)
        lit = Literature(
            project_id=project.id,
            zotero_item_key=item_key,
            zotero_subcollection_key=sub_key,
            outline_heading=heading or None,
            source_query=source_query,
            title=meta["title"],
            authors=meta["authors"] or None,
            year=meta["year"],
            doi=meta["doi"],
            abstract=meta["abstract"] or None,
            landing_url=meta["url"],
            relevance_score=raw.get("relevance_score"),
            selected_for_draft=True,
            confirmed_at=now,
        )
        db.add(lit)
        created.append(lit)

    await db.flush()
    for lit in created:
        await db.refresh(lit)
    return created
