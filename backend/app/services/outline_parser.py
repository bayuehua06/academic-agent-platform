"""论文大纲解析：Markdown `#` / Word Heading → outline JSON。"""

from __future__ import annotations

import re
from typing import Any, List, Optional

from docx import Document

HeadingItem = dict[str, Any]


_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def parse_markdown_outline(markdown_text: str) -> List[HeadingItem]:
    """
    从 Markdown 提取标题树为扁平列表。

    每项: {level: int, heading: str, key_points: str}
    key_points 为该标题下、下一标题前的正文。
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


def parse_docx_outline(docx_path: str) -> List[HeadingItem]:
    """从 Word 段落样式 Heading 1–6 提取大纲。"""
    doc = Document(docx_path)
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

    for para in doc.paragraphs:
        text = (para.text or "").strip()
        style = (para.style.name or "") if para.style else ""
        level = _heading_level_from_style(style)
        if level is not None and text:
            _flush()
            current = {"level": level, "heading": text, "key_points": ""}
            continue
        if current is not None and text:
            body_lines.append(text)
        elif current is not None and not text:
            body_lines.append("")

    _flush()
    # 若无 Heading 样式，回退：先转 markdown 再解析
    if not items:
        from app.services.pandoc_service import pandoc_service
        from pathlib import Path

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
