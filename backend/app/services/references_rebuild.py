"""确认精修时按文内引用重建 APA References。"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence, Set, Tuple

from app.agents.nodes.apa_formatter import format_apa_reference
from app.services.citation_guard import (
    _NARRATIVE,
    _PAREN_SEGMENT,
    _first_author_key,
    _norm_surname,
    _norm_year,
    SurnameYear,
    surname_of,
)
from app.services.pandoc_service import strip_references_section


def iter_intext_citation_keys(text: str) -> Set[SurnameYear]:
    """扫描正文中的文内引用，返回 (姓, 年) 集合。"""
    keys: Set[SurnameYear] = set()
    if not text:
        return keys

    for m in re.finditer(r"\(([^)]{3,200})\)", text):
        inner = m.group(1)
        if not re.search(r"(?:19|20)\d{2}|n\.d\.", inner, flags=re.I):
            continue
        if re.fullmatch(r"\s*pp?\.\s*\d+[-–]?\d*\s*", inner, flags=re.I):
            continue
        for seg in re.split(r"\s*;\s*", inner):
            sm = _PAREN_SEGMENT.match(seg.strip()) or _PAREN_SEGMENT.search(seg.strip())
            if not sm:
                continue
            sk = _first_author_key(sm.group("authors"))
            if len(sk) < 2:
                continue
            keys.add((sk, _norm_year(sm.group("year"))))

    for m in _NARRATIVE.finditer(text):
        sk = _first_author_key(m.group("authors"))
        if len(sk) < 2:
            continue
        keys.add((sk, _norm_year(m.group("year"))))
    return keys


def _source_keys(src: Dict[str, Any]) -> Set[SurnameYear]:
    authors = src.get("authors") or []
    if isinstance(authors, str):
        authors = [authors]
    year = _norm_year(str(src.get("year") or ""))
    out: Set[SurnameYear] = set()
    for a in authors:
        sn = _norm_surname(surname_of(str(a)))
        if sn:
            out.add((sn, year))
    if not out:
        out.add(("anonymous", year))
    return out


def rebuild_apa_references_from_citations(
    content_markdown: str,
    sources: Sequence[Dict[str, Any]],
) -> Tuple[str, str, List[str], int]:
    """
    按文内引用匹配文献库，生成 APA References block。

    Returns:
        (body_without_refs, apa_references_block, unmatched_labels, matched_count)
    """
    body = strip_references_section(content_markdown or "").strip() + "\n"
    cited = iter_intext_citation_keys(body)
    if not cited:
        return body, "", [], 0

    matched: List[Dict[str, Any]] = []
    matched_keys: Set[SurnameYear] = set()
    for src in sources or []:
        if not isinstance(src, dict):
            continue
        sk = _source_keys(src)
        if sk & cited:
            matched.append(src)
            matched_keys |= sk

    unmatched = sorted(f"{s}, {y}" for s, y in cited if (s, y) not in matched_keys)

    def sort_key(src: Dict[str, Any]) -> str:
        authors = src.get("authors") or ["Anonymous"]
        a0 = authors[0] if authors else "Anonymous"
        return surname_of(str(a0)).lower()

    matched_sorted = sorted(matched, key=sort_key)
    blocks = [format_apa_reference(s) for s in matched_sorted]  # type: ignore[arg-type]
    apa_block = "\n\n".join(f"  {b.replace(chr(10), chr(10) + '  ')}" for b in blocks)
    return body, apa_block, unmatched, len(matched_sorted)
