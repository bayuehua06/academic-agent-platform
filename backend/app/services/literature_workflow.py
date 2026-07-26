"""文献工作流编排：Zotero 结构对齐与确认入库。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Literature, Project
from app.services.zotero_service import ZoteroService, zotero_service

logger = logging.getLogger(__name__)


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


async def ensure_zotero_structure(
    project: Project,
    db: AsyncSession,
    zot: Optional[ZoteroService] = None,
) -> Dict[str, Any]:
    """
    创建/对齐项目顶层 Collection 与章节 Subcollection。

    要求已锁定 paper_outline；写回 projects.zotero_collection_id。
    """
    service = zot or zotero_service
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
        "subcollections": [
            {"outline_heading": h, "zotero_subcollection_key": k} for h, k in sub_map.items()
        ],
    }


async def sync_literatures_from_zotero(
    project: Project,
    db: AsyncSession,
    zot: Optional[ZoteroService] = None,
) -> List[Literature]:
    """
    以 Zotero 项目 Collection（含章节子集合）为真源，同步到本地 literatures。

    - 远程有、本地无 → 新建（confirmed_at 立即写入）
    - 两边都有 → 更新元数据
    - 本地有 zotero_item_key 但远程已无 → 删除本地镜像
    - 本地无 key 的残留（旧 mock）→ 删除
    """
    service = zot or zotero_service
    if not service.is_configured:
        raise RuntimeError("Zotero 未配置")

    if not project.zotero_collection_id:
        # 尝试按大纲建好空结构，便于之后离线添加
        headings = extract_outline_headings(project.paper_outline)
        if headings:
            await ensure_zotero_structure(project, db, zot=service)
        if not project.zotero_collection_id:
            raise ValueError(
                "项目尚无 Zotero Collection。请先完成至少一次文献确认入库，或调用 ensure-structure"
            )

    remote_items = service.fetch_project_collection_items(project.zotero_collection_id)
    now = datetime.now(timezone.utc)

    # 确保关系已加载
    existing_list = list(project.literatures or [])
    by_key: Dict[str, Literature] = {
        lit.zotero_item_key: lit for lit in existing_list if lit.zotero_item_key
    }
    seen_keys: set[str] = set()
    synced: List[Literature] = []

    for meta in remote_items:
        item_key = meta["zotero_item_key"]
        seen_keys.add(item_key)
        lit = by_key.get(item_key)
        if lit:
            lit.title = meta["title"]
            lit.authors = meta.get("authors") or None
            lit.year = meta.get("year")
            lit.doi = meta.get("doi")
            lit.abstract = meta.get("abstract")
            lit.outline_heading = meta.get("outline_heading")
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
                selected_for_draft=True,
                confirmed_at=now,
            )
            db.add(lit)
            by_key[item_key] = lit
        synced.append(lit)

    # 清理：远程已删除，或无 key 的本地残留
    for lit in existing_list:
        if not lit.zotero_item_key or lit.zotero_item_key not in seen_keys:
            await db.delete(lit)

    await db.flush()
    for lit in synced:
        await db.refresh(lit)

    logger.info(
        "Zotero→本地同步完成 project=%s remote=%s kept=%s",
        project.id,
        len(remote_items),
        len(synced),
    )
    return synced


async def import_confirmed_items(
    project: Project,
    db: AsyncSession,
    outline_heading: str,
    items: Sequence[Dict[str, Any]],
    source_query: Optional[str] = None,
    zot: Optional[ZoteroService] = None,
) -> List[Literature]:
    """
    将确认的候选写入 Zotero 对应章节子集合，并镜像到本地 literatures。

    Args:
        outline_heading: 必须与大纲某 heading 一致
        items: [{title, authors, year, doi, abstract, relevance_score?}, ...]
    """
    service = zot or zotero_service
    if not service.is_configured:
        raise RuntimeError("Zotero 未配置")

    heading = (outline_heading or "").strip()
    if not heading:
        raise ValueError("outline_heading 不能为空")

    headings = extract_outline_headings(project.paper_outline)
    if heading not in headings:
        raise ValueError(f"大纲中不存在章节: {heading!r}")

    structure = await ensure_zotero_structure(project, db, zot=service)
    sub_key = None
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
            "abstract": raw.get("abstract") or "",
        }
        item_key = service.create_item_from_meta(meta, collection_id=sub_key)
        lit = Literature(
            project_id=project.id,
            zotero_item_key=item_key,
            zotero_subcollection_key=sub_key,
            outline_heading=heading,
            source_query=source_query,
            title=meta["title"],
            authors=meta["authors"] or None,
            year=meta["year"],
            doi=meta["doi"],
            abstract=meta["abstract"] or None,
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
