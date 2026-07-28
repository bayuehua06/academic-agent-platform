"""大纲结构保真：节标题齐全 + key_points 内表格框架不得被散文替换。"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple


_TABLE_ROW = re.compile(r"^\s*\|.+\|\s*$", re.M)
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$", re.M)


def key_points_has_table(key_points: str) -> bool:
    """key_points 是否含 Markdown 表或明确表框架提示。"""
    text = key_points or ""
    if not text.strip():
        return False
    rows = _TABLE_ROW.findall(text)
    if len(rows) >= 2:
        return True
    if _TABLE_SEP.search(text) and len(rows) >= 1:
        return True
    # 中英文表提示 + 至少一行疑似表头
    low = text.lower()
    if any(k in low for k in ("| ---", "|---", "markdown table")):
        return True
    if re.search(r"(?:^|\n)\s*(?:table|表)\s*\d*\s*[:：.]", text, flags=re.I) and "|" in text:
        return True
    return False


def extract_seed_tables(key_points: str) -> List[str]:
    """从 key_points 抽出连续 Markdown 表块（含表头）。"""
    text = key_points or ""
    if not text.strip():
        return []
    lines = text.splitlines()
    tables: List[str] = []
    buf: List[str] = []
    for line in lines:
        if _TABLE_ROW.match(line) or _TABLE_SEP.match(line):
            buf.append(line)
        else:
            if len(buf) >= 2:
                tables.append("\n".join(buf))
            buf = []
    if len(buf) >= 2:
        tables.append("\n".join(buf))
    return tables


def _col_count(table_md: str) -> int:
    for line in (table_md or "").splitlines():
        if _TABLE_ROW.match(line) and not _TABLE_SEP.match(line):
            cells = [c for c in line.strip().strip("|").split("|")]
            return max(1, len(cells))
    return 0


def count_markdown_tables(text: str) -> int:
    return len(extract_seed_tables(text))


def find_section_span(draft: str, heading: str) -> Tuple[int, int, str]:
    """
    返回 (start_line_index, end_line_index, body_including_heading_line)。
    找不到则 (-1, -1, "")。
    """
    if not draft or not (heading or "").strip():
        return -1, -1, ""
    h = heading.strip()
    lines = draft.splitlines(keepends=True)
    start = -1
    start_level = 2
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if not m:
            continue
        if m.group(2).strip().lower() == h.lower():
            start = i
            start_level = len(m.group(1))
            break
    if start < 0:
        return -1, -1, ""
    end = len(lines)
    for j in range(start + 1, len(lines)):
        m = re.match(r"^(#{1,6})\s+", lines[j])
        if m and len(m.group(1)) <= start_level:
            end = j
            break
    chunk = "".join(lines[start:end])
    return start, end, chunk


def verify_outline_structure(
    draft: str,
    paper_outline: Sequence[Dict[str, Any]] | Sequence[Any],
) -> Dict[str, Any]:
    """
    校验：大纲各节标题出现；含表的 Seed 在对应节正文中保留表。

    Returns:
        ok, issues, missing_headings, missing_tables (list of heading)
    """
    issues: List[str] = []
    missing_headings: List[str] = []
    missing_tables: List[str] = []
    draft_l = (draft or "").lower()

    sections: List[Dict[str, Any]] = []
    for item in paper_outline or []:
        if isinstance(item, str):
            sections.append({"heading": item, "key_points": ""})
        elif isinstance(item, dict):
            h = (item.get("heading") or "").strip()
            if h:
                sections.append(
                    {
                        "heading": h,
                        "key_points": (item.get("key_points") or "").strip(),
                    }
                )

    for sec in sections:
        heading = sec["heading"]
        if heading.lower() not in draft_l and f"# {heading.lower()}" not in draft_l:
            # 标题行更严：找 heading 文本
            _, _, span = find_section_span(draft, heading)
            if not span:
                missing_headings.append(heading)
                continue
        else:
            _, _, span = find_section_span(draft, heading)
            if not span:
                # 标题字符串出现在别处但无独立标题行
                missing_headings.append(heading)
                continue

        kp = sec.get("key_points") or ""
        if not key_points_has_table(kp):
            continue
        seed_tables = extract_seed_tables(kp)
        need_cols = [_col_count(t) for t in seed_tables]
        need_cols = [c for c in need_cols if c > 0]
        body_tables = extract_seed_tables(span)
        if not body_tables:
            missing_tables.append(heading)
            continue
        if need_cols:
            body_cols = [_col_count(t) for t in body_tables]
            # 至少一张表列数与某一 seed 表接近（差 ≤1）
            ok_cols = False
            for nc in need_cols:
                for bc in body_cols:
                    if abs(bc - nc) <= 1:
                        ok_cols = True
                        break
                if ok_cols:
                    break
            if not ok_cols:
                missing_tables.append(heading)

    if missing_headings:
        issues.append(
            "Missing outline headings in draft: " + "; ".join(missing_headings[:12])
        )
    if missing_tables:
        issues.append(
            "Outline seed tables missing or distorted in sections: "
            + "; ".join(missing_tables[:12])
            + ". Restore Markdown tables with the same columns from OUTLINE SEED."
        )

    return {
        "ok": not issues,
        "issues": issues,
        "missing_headings": missing_headings,
        "missing_tables": missing_tables,
    }


def _normalize_outline_sections(
    paper_outline: Sequence[Dict[str, Any]] | Sequence[Any],
) -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []
    for item in paper_outline or []:
        if isinstance(item, str):
            h = item.strip()
            if h:
                sections.append({"level": 1, "heading": h, "key_points": ""})
        elif isinstance(item, dict):
            h = (item.get("heading") or "").strip()
            if not h:
                continue
            sections.append(
                {
                    "level": int(item.get("level") or 1),
                    "heading": h,
                    "key_points": (item.get("key_points") or "").strip(),
                }
            )
    return sections


def force_section_heading(body: str, *, heading: str, level: int = 1) -> str:
    """
    强制本节以大纲标题开头：去掉开头错误/多余标题行，再 prepend 正确 heading。
    """
    title = (heading or "").strip() or "Section"
    hashes = "#" * max(1, min(int(level or 1), 6))
    heading_line = f"{hashes} {title}"
    text = (body or "").strip()
    if not text:
        return heading_line + "\n\n"

    lines = text.splitlines()
    # 剥离开头连续标题行（中间空行可跳过），直到遇到正文或匹配大纲标题
    while lines:
        if not lines[0].strip():
            lines = lines[1:]
            continue
        m = re.match(r"^(#{1,6})\s+(.+?)\s*$", lines[0].strip())
        if not m:
            break
        h = m.group(2).strip()
        lines = lines[1:]
        if h.lower() == title.lower():
            break
        # 丢弃 Academic Draft / 改写后的错误标题等
    # 再清掉标题后残留空行
    while lines and not lines[0].strip():
        lines = lines[1:]
    rest = "\n".join(lines).strip()
    if rest:
        return f"{heading_line}\n\n{rest}\n"
    return heading_line + "\n\n"


def strip_nested_outline_headings(
    body: str,
    outline_headings: Sequence[str],
    *,
    keep_heading: str,
) -> str:
    """
    从本节正文中去掉「其它大纲标题」及其下属块。
    防止父节 LLM 输出里夹带子节标题，与后续分节写作重复拼接。
    """
    keep = (keep_heading or "").strip().lower()
    locked = {
        (h or "").strip().lower()
        for h in outline_headings
        if (h or "").strip() and (h or "").strip().lower() != keep
    }
    if not locked or not (body or "").strip():
        return (body or "").strip()

    lines = (body or "").splitlines()
    out: List[str] = []
    skip_level: Optional[int] = None
    for line in lines:
        m = re.match(r"^(#{1,6})\s+(.+?)\s*$", line.strip())
        if m:
            level = len(m.group(1))
            title = m.group(2).strip().lower()
            if skip_level is not None and level <= skip_level:
                skip_level = None
            if skip_level is None and title in locked:
                skip_level = level
                continue
            if skip_level is not None:
                continue
        elif skip_level is not None:
            continue
        out.append(line)
    return "\n".join(out).strip()


def _collect_exclusive_outline_bodies(
    draft: str,
    sections: Sequence[Dict[str, Any]],
) -> Dict[str, List[str]]:
    """
    按「任意大纲标题」切分草稿，得到互不重叠的正文块。
    同一标题出现多次时保留全部（重建时取最后一次，优先分节专写结果）。
    """
    titles = {
        (sec.get("heading") or "").strip().lower()
        for sec in sections
        if (sec.get("heading") or "").strip()
    }
    if not titles:
        return {}

    lines = (draft or "").splitlines(keepends=True)
    cuts: List[Tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if not m:
            continue
        key = m.group(2).strip().lower()
        if key in titles:
            cuts.append((i, key))

    bodies: Dict[str, List[str]] = {t: [] for t in titles}
    for ci, (start, key) in enumerate(cuts):
        end = cuts[ci + 1][0] if ci + 1 < len(cuts) else len(lines)
        chunk = "".join(lines[start + 1 : end]).strip()
        bodies.setdefault(key, []).append(chunk)
    return bodies


def rebuild_draft_to_outline(
    draft: str,
    paper_outline: Sequence[Dict[str, Any]] | Sequence[Any],
    *,
    inject_missing_seed_tables: bool = True,
) -> str:
    """
    按锁定大纲确定性重建标题骨架：顺序/级别/标题文本以大纲为准。
    找不到的节用占位；缺表时可回填 seed 表框架。

    关键：不得用「同级或更高级标题」作为父节终点（会把子节吞进父节），
    再按大纲追加子节 → 子节重复；多次 rebuild 会指数叠加。
    改为按任意大纲标题做互斥切分，同一标题多次出现时取最后一次。
    """
    sections = _normalize_outline_sections(paper_outline)
    if not sections:
        return (draft or "").strip() + ("\n" if draft else "")

    outline_headings = [sec["heading"] for sec in sections]
    exclusive = _collect_exclusive_outline_bodies(draft or "", sections)

    parts: List[str] = []
    for sec in sections:
        heading = sec["heading"]
        level = int(sec.get("level") or 1)
        hashes = "#" * max(1, min(level, 6))
        key = heading.strip().lower()
        chunks = exclusive.get(key) or []
        if chunks:
            # 分节写作时：父节若误含子标题，专写子节通常在后；取最后一次
            body = chunks[-1]
        else:
            body = (
                "*(Section restored deterministically: the model draft was missing "
                "this locked outline heading.)*"
            )

        body = strip_nested_outline_headings(
            body, outline_headings, keep_heading=heading
        )

        kp = sec.get("key_points") or ""
        if (
            inject_missing_seed_tables
            and key_points_has_table(kp)
            and not extract_seed_tables(body)
        ):
            seeds = extract_seed_tables(kp)
            if seeds:
                body = ((body + "\n\n") if body else "") + "\n\n".join(seeds)

        if body:
            parts.append(f"{hashes} {heading}\n\n{body}\n")
        else:
            parts.append(f"{hashes} {heading}\n")
    return "\n".join(parts).strip() + "\n"


def format_verification_issues_for_changelog(verification: Optional[Dict[str, Any]]) -> str:
    """把 writer_verification 压成 changelog 可读片段。"""
    v = verification or {}
    chunks: List[str] = []
    issues = [str(i).strip() for i in (v.get("issues") or []) if str(i).strip()]
    if issues:
        joined = " | ".join(issues[:5])
        if len(joined) > 500:
            joined = joined[:497] + "..."
        chunks.append(f"issues={joined}")
    structure = v.get("structure") or {}
    missing_h = [str(x) for x in (structure.get("missing_headings") or []) if x]
    missing_t = [str(x) for x in (structure.get("missing_tables") or []) if x]
    if missing_h:
        chunks.append("missing_headings=" + "; ".join(missing_h[:8]))
    if missing_t:
        chunks.append("missing_tables=" + "; ".join(missing_t[:8]))
    missing_mi = [str(x) for x in (v.get("missing_must_include") or []) if x]
    if missing_mi:
        chunks.append("missing_must_include=" + "; ".join(missing_mi[:6]))
    if v.get("citation_ok") is False:
        hall = v.get("hallucinated_citations") or []
        if hall:
            chunks.append("bad_citations=" + "; ".join(str(x) for x in hall[:5]))
        else:
            chunks.append("citation_ok=False")
    return "; ".join(chunks)


def format_table_seed_hint(key_points: str) -> str:
    """写入本节 user 提示的表硬要求块。"""
    if not key_points_has_table(key_points):
        return ""
    tables = extract_seed_tables(key_points)
    if not tables:
        return (
            "STRUCTURE HARD RULE: This section's OUTLINE SEED implies a table. "
            "You MUST output at least one Markdown pipe table in this section "
            "(do not replace it with prose only). "
            "All table headers and cell text MUST be academic English "
            "(translate any Chinese draft notes; do not leave Chinese in the table).\n"
        )
    blocks = "\n\n".join(f"Seed table framework {i + 1}:\n{t}" for i, t in enumerate(tables[:3]))
    return (
        "STRUCTURE HARD RULE: Preserve the following Markdown table framework(s).\n"
        "- Keep the same columns and comparable row structure (do NOT replace the table with prose only).\n"
        "- LANGUAGE: The final table MUST be entirely academic English. "
        "Chinese (or other non-English) text in the seed is a private draft/hint only — "
        "TRANSLATE and rewrite it into English; do NOT copy Chinese cells verbatim.\n"
        "- You may expand/clarify cell content in English while keeping the column layout.\n\n"
        f"{blocks}\n"
    )
