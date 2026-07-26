"""Node 3: APA Writer — 严格按 paper_outline 生成带引用的 Markdown 草稿。"""

from __future__ import annotations

import logging
from typing import List

from app.agents.state import AcademicAgentState, LiteratureSource, OutlineSection

logger = logging.getLogger(__name__)


def format_intext_citation(authors: List[str], year: str) -> str:
    """
    APA 7th 文内引用：
    - 单作者: (Smith, 2024)
    - 双作者: (Zhang & Li, 2024)
    - 三作者及以上: (Wang et al., 2023)
    """
    year = year or "n.d."
    if not authors:
        return f"(Anonymous, {year})"

    def surname(name: str) -> str:
        name = name.strip()
        if "," in name:
            return name.split(",")[0].strip()
        parts = name.split()
        return parts[-1] if parts else name

    surnames = [surname(a) for a in authors]
    if len(surnames) == 1:
        return f"({surnames[0]}, {year})"
    if len(surnames) == 2:
        return f"({surnames[0]} & {surnames[1]}, {year})"
    return f"({surnames[0]} et al., {year})"


def _heading_md(level: int, title: str) -> str:
    return f"{'#' * max(1, min(int(level or 1), 6))} {title}"


def _section_paragraph(
    section: OutlineSection,
    sources: List[LiteratureSource],
    index: int,
) -> str:
    """按大纲节生成带层级标题与要点提示的段落。"""
    title = section.get("heading") or f"Section {index + 1}"
    level = int(section.get("level") or 1)
    key_points = (section.get("key_points") or "").strip()
    heading = _heading_md(level, title)

    focus = key_points[:400] if key_points else title

    if not sources:
        return (
            f"{heading}\n\n"
            f"This section addresses {focus}. Further empirical support should be "
            f"integrated as sources become available.\n"
        )

    src = sources[index % len(sources)]
    cite = format_intext_citation(src.get("authors") or [], src.get("year") or "")
    topic = src.get("title", "prior research")
    points_line = f" Section focus: {key_points[:300]}." if key_points else ""
    return (
        f"{heading}\n\n"
        f"Recent scholarship on this topic highlights key debates surrounding "
        f"*{topic}* {cite}.{points_line} Building on these findings, the present "
        f"discussion synthesizes methodological insights and situates them within "
        f"the assessment framework.\n"
    )


def write_apa_draft(state: AcademicAgentState) -> AcademicAgentState:
    """APA Writer：优先严格遍历 paper_outline；否则回退 outline 字符串列表。"""
    logger.info("Agent step: write_apa_draft (project=%s)", state.get("project_id"))

    paper_outline = state.get("paper_outline") or []
    if not paper_outline:
        paper_outline = [
            {"level": 1, "heading": h, "key_points": ""}
            for h in (state.get("outline") or ["Introduction", "Discussion", "Conclusion"])
        ]

    sources = state.get("sources") or []
    requirements = (
        (state.get("assessment_summary") or "").strip()
        or (state.get("assessment_requirements") or "").strip()
    )
    specific = (state.get("specific_requirements") or "").strip()
    keywords = state.get("keywords") or []

    intro_extra = ""
    if requirements:
        intro_extra += f"\n\nAssessment focus: {requirements[:500]}\n"
    if specific:
        intro_extra += f"\nSpecific requirements: {specific[:400]}\n"

    parts = [
        "# Academic Draft\n",
        f"*Keywords: {', '.join(keywords)}*\n",
        intro_extra,
    ]
    for i, section in enumerate(paper_outline):
        if isinstance(section, str):
            section = {"level": 1, "heading": section, "key_points": ""}
        parts.append(_section_paragraph(section, sources, i))

    draft = "\n".join(parts).strip() + "\n"
    return {
        **state,
        "draft_markdown": draft,
        "current_step": "write_apa_draft",
        "error": None,
    }
