"""论文大纲解析：Markdown `#` / Word Heading → outline JSON。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterator, List, Optional, Union

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.services.word_package import normalize_word_package_inplace

HeadingItem = dict[str, Any]

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def parse_markdown_outline(markdown_text: str) -> List[HeadingItem]:
    """
    从 Markdown 提取标题树为扁平列表。

    每项: {level: int, heading: str, key_points: str}
    key_points 为该标题下、下一标题前的正文（含 Markdown 表格行）。
    """
    lines = (markdown_text or "").replace("\r\n", "\n").split("\n")
    items: List[HeadingItem] = []
    current: Optional[HeadingItem] = None
    body_lines: list[str] = []

    def _flush() -> None:
        nonlocal current, body_lines
        if current is None:
            body_lines = []
            return
        current["key_points"] = "\n".join(body_lines).strip()
        items.append(current)
        current = None
        body_lines = []

    for line in lines:
        m = _MD_HEADING.match(line)
        if m:
            _flush()
            current = {
                "level": len(m.group(1)),
                "heading": m.group(2).strip(),
                "key_points": "",
            }
            continue
        if current is not None:
            body_lines.append(line)

    _flush()
    return items


def _iter_block_items(doc: Document) -> Iterator[Union[Paragraph, Table]]:
    """按文档顺序遍历段落与表格（python-docx 默认 paragraphs 不含表）。"""
    body = doc.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield Table(child, doc)


def _table_to_text_lines(table: Table) -> List[str]:
    """表格 → 纯文本行（优先 Markdown 表；空行跳过）。"""
    rows: List[List[str]] = []
    for row in table.rows:
        cells: List[str] = []
        for cell in row.cells:
            # 单元格内多段合并
            cell_text = " ".join(
                (p.text or "").strip() for p in cell.paragraphs if (p.text or "").strip()
            )
            cells.append(cell_text.replace("|", "\\|").replace("\n", " "))
        if any(c.strip() for c in cells):
            rows.append(cells)
    if not rows:
        return []

    # 统一列数
    width = max(len(r) for r in rows)
    norm = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(r) + " |" for r in norm]
    if len(norm) >= 1:
        sep = "| " + " | ".join("---" for _ in range(width)) + " |"
        lines.insert(1, sep)
    return lines


def parse_docx_outline(docx_path: str) -> List[HeadingItem]:
    """
    从 Word 按文档顺序提取大纲。

    - Heading 1–6 / 标题 1–6 → 章节
    - 标题下的普通段落 + **表格文字** → key_points
    """
    path = Path(docx_path)
    normalize_word_package_inplace(path)
    doc = Document(str(path))
    items: List[HeadingItem] = []
    current: Optional[HeadingItem] = None
    body_lines: list[str] = []

    def _flush() -> None:
        nonlocal current, body_lines
        if current is None:
            body_lines = []
            return
        current["key_points"] = "\n".join(body_lines).strip()
        items.append(current)
        current = None
        body_lines = []

    for block in _iter_block_items(doc):
        if isinstance(block, Paragraph):
            text = (block.text or "").strip()
            style = (block.style.name or "") if block.style else ""
            level = _heading_level_from_style(style)
            if level is not None and text:
                _flush()
                current = {"level": level, "heading": text, "key_points": ""}
                continue
            if current is not None:
                body_lines.append(text if text else "")
            continue

        if isinstance(block, Table):
            # 尚无标题时：若整篇以表开头，先建占位节，避免表内文字丢失
            if current is None:
                current = {
                    "level": 1,
                    "heading": "(Untitled)",
                    "key_points": "",
                }
            table_lines = _table_to_text_lines(block)
            if table_lines:
                if body_lines and body_lines[-1].strip():
                    body_lines.append("")
                body_lines.extend(table_lines)
                body_lines.append("")

    _flush()

    # 若无任何 Heading，回退：转 Markdown 再解析（含表）
    has_real_heading = any(i["heading"] != "(Untitled)" for i in items)
    if not has_real_heading:
        from app.services.pandoc_service import pandoc_service

        md = pandoc_service.docx_to_markdown(Path(docx_path))
        return parse_markdown_outline(md)
    return items


def parse_outline_from_raw(
    raw_text: str,
    *,
    storage_path: Optional[str] = None,
    original_filename: Optional[str] = None,
) -> List[HeadingItem]:
    """优先用 docx 路径解析 Heading；否则按 Markdown 标题解析。"""
    name = (original_filename or "").lower()
    if storage_path and (name.endswith(".docx") or storage_path.lower().endswith(".docx")):
        items = parse_docx_outline(storage_path)
        if items:
            return items
    return parse_markdown_outline(raw_text or "")


def _heading_level_from_style(style_name: str) -> Optional[int]:
    lowered = (style_name or "").lower().strip()
    # "Heading 1" / "标题 1"
    m = re.search(r"(?:heading|标题)\s*(\d)", lowered)
    if m:
        level = int(m.group(1))
        return level if 1 <= level <= 6 else None
    return None
