"""Node 1: 需求分析 — 提取关键词与写作大纲。"""

from __future__ import annotations

import logging
import re
from typing import List

from app.agents.state import AcademicAgentState

logger = logging.getLogger(__name__)


def _extract_keywords(text: str, limit: int = 8) -> List[str]:
    """简易关键词提取：英文短语 + 中文 2–6 字词。"""
    keywords: List[str] = []
    # 引号内短语优先
    quoted = re.findall(r'["""]([^"""]+)["""]', text)
    keywords.extend(q.strip() for q in quoted if len(q.strip()) > 2)

    # 英文多词短语
    en_phrases = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Za-z]+){0,3})\b", text)
    keywords.extend(en_phrases)

    # 中文关键词候选
    cn = re.findall(r"[\u4e00-\u9fff]{2,6}", text)
    keywords.extend(cn)

    # 去重保序
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


def _build_outline(requirements: str, notebook: str) -> List[str]:
    """根据评估要求生成默认 APA 论文大纲。"""
    base = [
        "Introduction",
        "Literature Review",
        "Methodology",
        "Discussion",
        "Conclusion",
    ]
    # 若文本提及特定章节则优先保留
    combined = f"{requirements}\n{notebook}".lower()
    extras = []
    if "case study" in combined or "案例" in combined:
        extras.append("Case Study Analysis")
    if "limitation" in combined or "局限" in combined:
        extras.append("Limitations")
    if "recommendation" in combined or "建议" in combined:
        extras.append("Recommendations")
    return base + extras


def analyze_requirements(state: AcademicAgentState) -> AcademicAgentState:
    """
    Requirement Analyzer 节点。

    结合 assessment_requirements 与 notebook_context，输出 keywords 与 outline。
    若配置了 OPENAI_API_KEY，可后续替换为 LLM 增强版。
    """
    logger.info("Agent step: analyze_requirements (project=%s)", state.get("project_id"))
    requirements = state.get("assessment_requirements") or ""
    notebook = state.get("notebook_context") or ""
    combined = f"{requirements}\n\n{notebook}"

    keywords = _extract_keywords(combined)
    outline = _build_outline(requirements, notebook)

    return {
        **state,
        "keywords": keywords,
        "outline": outline,
        "current_step": "analyze_requirements",
        "error": None,
    }
