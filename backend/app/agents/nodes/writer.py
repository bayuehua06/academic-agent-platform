"""Node 3: APA Writer — 生成带 In-text Citation 的 Markdown 草稿。"""

from __future__ import annotations

import logging
from typing import List

from app.agents.state import AcademicAgentState, LiteratureSource

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
        # "Smith, J." / "John Smith" / "Zhang, W."
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


def _section_paragraph(title: str, sources: List[LiteratureSource], index: int) -> str:
    """为大纲章节生成带引用的段落。"""
    if not sources:
        return (
            f"## {title}\n\n"
            f"This section addresses {title.lower()} in relation to the assessment "
            f"requirements. Further empirical support should be integrated as sources "
            f"become available.\n"
        )

    src = sources[index % len(sources)]
    cite = format_intext_citation(src.get("authors") or [], src.get("year") or "")
    topic = src.get("title", "prior research")
    return (
        f"## {title}\n\n"
        f"Recent scholarship on this topic highlights key debates surrounding "
        f"*{topic}* {cite}. Building on these findings, the present discussion "
        f"synthesizes methodological insights and situates them within the assessment "
        f"framework. The evidence suggests that careful operationalization of constructs "
        f"and transparent reporting practices strengthen the credibility of academic "
        f"arguments in this domain.\n"
    )


def write_apa_draft(state: AcademicAgentState) -> AcademicAgentState:
    """APA Writer 节点：按大纲生成 Markdown 正文。"""
    logger.info("Agent step: write_apa_draft (project=%s)", state.get("project_id"))

    outline = state.get("outline") or ["Introduction", "Discussion", "Conclusion"]
    sources = state.get("sources") or []
    requirements = (state.get("assessment_requirements") or "").strip()
    keywords = state.get("keywords") or []

    intro_extra = ""
    if requirements:
        intro_extra = (
            f"\n\nAssessment focus: {requirements[:500]}\n"
        )

    parts = [
        "# Academic Draft\n",
        f"*Keywords: {', '.join(keywords)}*\n",
        intro_extra,
    ]
    for i, section in enumerate(outline):
        parts.append(_section_paragraph(section, sources, i))

    draft = "\n".join(parts).strip() + "\n"
    return {
        **state,
        "draft_markdown": draft,
        "current_step": "write_apa_draft",
        "error": None,
    }
