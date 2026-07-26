"""Node 2: 文献检索 — browser-use / 模拟检索 + Zotero DOI 同步。"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List

from app.agents.state import AcademicAgentState, LiteratureSource
from app.core.config import get_settings
from app.services.zotero_service import zotero_service

logger = logging.getLogger(__name__)
settings = get_settings()


def _mock_search(keywords: List[str], max_papers: int) -> List[LiteratureSource]:
    """
    无浏览器/API 时的确定性模拟检索结果，便于本地联调。

    生产环境应替换为 browser-use（IEEE / Scholar）或官方 API。
    """
    seed = "|".join(keywords) or "academic"
    sources: List[LiteratureSource] = []
    sample_authors = [
        ["Smith, J."],
        ["Zhang, W.", "Li, Y."],
        ["Wang, H.", "Chen, L.", "Liu, M."],
        ["Brown, A.", "Davis, K."],
        ["Garcia, R."],
    ]
    for i in range(max_papers):
        digest = hashlib.md5(f"{seed}-{i}".encode()).hexdigest()[:8]
        authors = sample_authors[i % len(sample_authors)]
        year = str(2020 + (i % 5))
        title = f"{keywords[i % len(keywords)].title()} in Contemporary Research ({digest})"
        sources.append(
            LiteratureSource(
                title=title,
                authors=authors,
                year=year,
                doi=f"10.1000/academic.{digest}",
                abstract=(
                    f"This paper examines {keywords[i % len(keywords)]} "
                    f"with implications for academic practice. Methodological "
                    f"considerations and empirical findings are discussed."
                ),
                relevance_score=round(0.95 - i * 0.08, 2),
                zotero_item_key=None,
            )
        )
    return sources


def _search_with_browser(keywords: List[str], max_papers: int) -> List[LiteratureSource]:
    """
    使用 browser-use + Chrome Profile 检索（可选扩展）。

    未配置 CHROME_USER_DATA_DIR 时回退到 mock。
    """
    if not settings.chrome_user_data_dir:
        logger.info("未配置 Chrome Profile，使用模拟检索")
        return _mock_search(keywords, max_papers)

    try:
        # 预留：browser-use Agent 驱动 Scholar / IEEE 搜索
        # from browser_use import Agent
        logger.warning("browser-use 检索尚未完全接入，回退模拟数据")
        return _mock_search(keywords, max_papers)
    except Exception as exc:  # noqa: BLE001
        logger.error("浏览器检索失败: %s", exc)
        return _mock_search(keywords, max_papers)


def _sync_zotero(sources: List[LiteratureSource], collection_id: str | None) -> List[LiteratureSource]:
    """将文献 DOI 写入 Zotero，回填 item_key。"""
    synced: List[LiteratureSource] = []
    for src in sources:
        meta: Dict[str, Any] = {
            "title": src.get("title"),
            "authors": src.get("authors"),
            "year": src.get("year"),
            "doi": src.get("doi"),
            "abstract": src.get("abstract"),
        }
        item_key = None
        doi = src.get("doi")
        if doi and zotero_service.is_configured:
            item_key = zotero_service.add_item_by_doi(
                doi, collection_id=collection_id, fallback_meta=meta
            )
        updated = {**src, "zotero_item_key": item_key}
        synced.append(LiteratureSource(**updated))
    return synced


def search_literature(state: AcademicAgentState) -> AcademicAgentState:
    """Literature Searcher：关键词优先来自 A，并并入 C 各节标题。"""
    logger.info("Agent step: search_literature (project=%s)", state.get("project_id"))

    if state.get("skip_search") and state.get("sources"):
        return {**state, "current_step": "search_literature"}

    keywords = list(state.get("keywords") or [])
    for section in state.get("paper_outline") or []:
        if isinstance(section, dict):
            heading = (section.get("heading") or "").strip()
            if heading and heading not in keywords:
                keywords.append(heading)
        elif isinstance(section, str) and section.strip():
            keywords.append(section.strip())
    if not keywords:
        keywords = ["academic research"]

    max_papers = int(state.get("max_papers") or 5)
    sources = _search_with_browser(keywords, max_papers)
    sources = _sync_zotero(sources, state.get("zotero_collection_id"))

    return {
        **state,
        "keywords": keywords,
        "sources": sources,
        "current_step": "search_literature",
        "error": None,
    }
