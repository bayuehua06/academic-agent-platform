"""Node 1: 需求分析 — 提取关键词与写作大纲。"""

from __future__ import annotations

import logging
import re
from typing import Any, List

from app.agents.state import AcademicAgentState, OutlineSection

logger = logging.getLogger(__name__)


def _extract_keywords(text: str, limit: int = 8) -> List[str]:
    """简易关键词提取：英文短语 + 中文 2–6 字词。"""
    keywords: List[str] = []
    quoted = re.findall(r'["""]([^"""]+)["""]', text)
    keywords.extend(q.strip() for q in quoted if len(q.strip()) > 2)

    en_phrases = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Za-z]+){0,3})\b", text)
    keywords.extend(en_phrases)

    cn = re.findall(r"[\u4e00-\u9fff]{2,6}", text)
    keywords.extend(cn)

    seen = set()
    unique: List[str] = []
    for kw in keywords:
        key = kw.lower()
        if key not in seen and len(kw) > 1:
            seen.add(key)
            unique.append(kw)
        if len(unique) >= limit:
            break

    if not unique:
        unique = ["academic writing", "literature review", "research methodology"]
    return unique


def _build_outline(requirements: str, extra: str) -> List[str]:
    """无锁定大纲时的默认 APA 章节。"""
    base = [
        "Introduction",
        "Literature Review",
        "Methodology",
        "Discussion",
        "Conclusion",
    ]
    combined = f"{requirements}\n{extra}".lower()
    extras = []
    if "case study" in combined or "案例" in combined:
        extras.append("Case Study Analysis")
    if "limitation" in combined or "局限" in combined:
        extras.append("Limitations")
    if "recommendation" in combined or "建议" in combined:
        extras.append("Recommendations")
    return base + extras


def _resolve_assessment(state: AcademicAgentState) -> str:
    return (
        (state.get("assessment_summary") or "").strip()
        or (state.get("assessment_requirements") or "").strip()
    )


def _resolve_background_text(state: AcademicAgentState) -> str:
    parts = [p.strip() for p in (state.get("background_summaries") or []) if p and str(p).strip()]
    if parts:
        return "\n\n".join(parts)
    return (state.get("notebook_context") or "").strip()


def _normalize_paper_outline(raw: Any) -> List[OutlineSection]:
    if not isinstance(raw, list):
        return []
    items: List[OutlineSection] = []
    for entry in raw:
        if isinstance(entry, str) and entry.strip():
            items.append({"level": 1, "heading": entry.strip(), "key_points": ""})
            continue
        if not isinstance(entry, dict):
            continue
        heading = str(entry.get("heading") or "").strip()
        if not heading:
            continue
        try:
            level = int(entry.get("level") or 1)
        except (TypeError, ValueError):
            level = 1
        items.append(
            {
                "level": max(1, min(level, 6)),
                "heading": heading,
                "key_points": str(entry.get("key_points") or "").strip(),
            }
        )
    return items


def analyze_requirements(state: AcademicAgentState) -> AcademicAgentState:
    """
    Requirement Analyzer。

    优先级：A 定稿 > C 锁定大纲 > B 背景 > D 具体要求。
    若已有 paper_outline，严格以其 headings 作为写作大纲。
    """
    logger.info("Agent step: analyze_requirements (project=%s)", state.get("project_id"))
    assessment = _resolve_assessment(state)
    specific = (state.get("specific_requirements") or "").strip()
    background = _resolve_background_text(state)
    # 关键词优先级 A > C headings > B > D
    paper_outline = _normalize_paper_outline(state.get("paper_outline"))
    outline_text = " ".join(item["heading"] for item in paper_outline)
    combined = "\n\n".join(
        part for part in [assessment, outline_text, background, specific] if part
    )

    keywords = _extract_keywords(combined)

    if paper_outline:
        outline = [item["heading"] for item in paper_outline]
    else:
        outline = _build_outline(assessment, f"{background}\n{specific}")
        paper_outline = [
            {"level": 1, "heading": h, "key_points": ""} for h in outline
        ]

    return {
        **state,
        "assessment_summary": assessment,
        "specific_requirements": specific,
        "background_summaries": state.get("background_summaries")
        or ([background] if background else []),
        "paper_outline": paper_outline,
        "keywords": keywords,
        "outline": outline,
        "current_step": "analyze_requirements",
        "error": None,
    }
