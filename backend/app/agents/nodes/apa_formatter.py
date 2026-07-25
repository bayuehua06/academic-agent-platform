"""Node 4: APA Formatter — 生成 APA 7th References 列表。"""

from __future__ import annotations

import logging
import re
from typing import List, Tuple

from app.agents.state import AcademicAgentState, LiteratureSource

logger = logging.getLogger(__name__)


def _parse_author(name: str) -> Tuple[str, str]:
    """解析作者为 (surname, initials)。"""
    name = name.strip()
    if "," in name:
        # "Smith, J." 或 "Smith, John"
        surname, rest = name.split(",", 1)
        rest = rest.strip()
        initials = "".join(p[0].upper() + "." for p in re.findall(r"[A-Za-z]+", rest))
        return surname.strip(), initials or "X."
    parts = name.split()
    if len(parts) == 1:
        return parts[0], "X."
    surname = parts[-1]
    initials = "".join(p[0].upper() + "." for p in parts[:-1])
    return surname, initials


def format_author_list(authors: List[str]) -> str:
    """APA 7th 作者列表格式化。"""
    if not authors:
        return "Anonymous"
    parsed = [_parse_author(a) for a in authors]
    formatted = [f"{s}, {i}" for s, i in parsed]
    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) == 2:
        return f"{formatted[0]}, & {formatted[1]}"
    # 3–20 作者：逗号分隔，最后前加 &
    return ", ".join(formatted[:-1]) + f", & {formatted[-1]}"


def format_apa_reference(source: LiteratureSource) -> str:
    """
    单条 APA 7th 期刊条目（Markdown，斜体标题用 *...*）。

    示例:
    Smith, J. (2024). *Title of article*. Journal placeholder.
    https://doi.org/10.1000/xxx
    """
    authors = format_author_list(source.get("authors") or [])
    year = source.get("year") or "n.d."
    title = (source.get("title") or "Untitled").rstrip(".")
    doi = source.get("doi")
    doi_line = f"https://doi.org/{doi}" if doi else ""
    # Markdown hanging indent 用 blockquote / 空格近似
    lines = [
        f"{authors} ({year}). *{title}*. Academic Sources Archive.",
    ]
    if doi_line:
        lines.append(doi_line)
    return "\n".join(lines)


def format_apa_references(state: AcademicAgentState) -> AcademicAgentState:
    """APA Formatter 节点：按作者姓氏排序生成 References。"""
    logger.info("Agent step: format_apa_references (project=%s)", state.get("project_id"))

    sources = list(state.get("sources") or [])

    def sort_key(src: LiteratureSource) -> str:
        authors = src.get("authors") or ["Anonymous"]
        surname, _ = _parse_author(authors[0])
        return surname.lower()

    sources_sorted = sorted(sources, key=sort_key)
    blocks = [format_apa_reference(s) for s in sources_sorted]
    # 挂起缩进：用两个空格前缀 + 空行分隔（Markdown 可读近似）
    apa_block = "\n\n".join(f"  {b.replace(chr(10), chr(10) + '  ')}" for b in blocks)

    return {
        **state,
        "apa_references": apa_block,
        "sources": sources_sorted,
        "current_step": "format_apa_references",
        "error": None,
    }
