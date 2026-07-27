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


def format_table_seed_hint(key_points: str) -> str:
    """写入本节 user 提示的表硬要求块。"""
    if not key_points_has_table(key_points):
        return ""
    tables = extract_seed_tables(key_points)
    if not tables:
        return (
            "STRUCTURE HARD RULE: This section's OUTLINE SEED implies a table. "
            "You MUST output at least one Markdown pipe table in this section "
            "(do not replace it with prose only).\n"
        )
    blocks = "\n\n".join(f"Seed table framework {i + 1}:\n{t}" for i, t in enumerate(tables[:3]))
    return (
        "STRUCTURE HARD RULE: Preserve the following Markdown table framework(s). "
        "Keep the same columns/headers; you may fill cells with content. "
        "Do NOT convert the table into paragraphs only.\n\n"
        f"{blocks}\n"
    )
