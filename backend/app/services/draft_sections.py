"""草稿 Markdown 分节、图/表锁定块、节替换。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple


_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$")
_TABLE_LINE_RE = re.compile(r"^\s*\|.*\|\s*$")
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
_FIGURE_PLACEHOLDER_RE = re.compile(
    r"^\[?\s*(Figure|Table|图|表)\s*\d+[:：.].*\]?\s*$",
    re.I,
)
_LOCKED_TOKEN_RE = re.compile(r"<<LOCKED_(\d+)>>")


@dataclass
class DraftSection:
    """一篇草稿中的一个标题节。"""

    heading: str
    level: int
    body: str  # 不含标题行
    start_line: int
    end_line: int  # exclusive
    has_locked_blocks: bool = False
    locked_count: int = 0

    @property
    def full_markdown(self) -> str:
        hashes = "#" * self.level
        if self.body.strip():
            return f"{hashes} {self.heading}\n\n{self.body.strip()}\n"
        return f"{hashes} {self.heading}\n"


@dataclass
class LockExtractResult:
    editable: str
    locked_blocks: List[str] = field(default_factory=list)


def split_markdown_sections(markdown: str) -> List[DraftSection]:
    """按 # / ## / ### 拆节；无标题时整篇为 Untitled。"""
    text = markdown or ""
    lines = text.splitlines()
    if not lines:
        return []

    indices: List[Tuple[int, int, str]] = []
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line.strip())
        if m:
            indices.append((i, len(m.group(1)), m.group(2).strip()))

    if not indices:
        body = text.strip()
        locked = detect_locked_in_text(body)
        return [
            DraftSection(
                heading="(Untitled)",
                level=1,
                body=body,
                start_line=0,
                end_line=len(lines),
                has_locked_blocks=locked > 0,
                locked_count=locked,
            )
        ]

    sections: List[DraftSection] = []
    for j, (start, level, heading) in enumerate(indices):
        end = indices[j + 1][0] if j + 1 < len(indices) else len(lines)
        body_lines = lines[start + 1 : end]
        # 去掉节末多余空行
        while body_lines and not body_lines[-1].strip():
            body_lines.pop()
        body = "\n".join(body_lines).strip()
        locked = detect_locked_in_text(body)
        sections.append(
            DraftSection(
                heading=heading,
                level=level,
                body=body,
                start_line=start,
                end_line=end,
                has_locked_blocks=locked > 0,
                locked_count=locked,
            )
        )
    return sections


def detect_locked_in_text(text: str) -> int:
    """统计可识别的锁定块数量（粗略）。"""
    return len(extract_locked_blocks(text).locked_blocks)


def extract_locked_blocks(text: str) -> LockExtractResult:
    """
    将表 / 图占位替换为 <<LOCKED_n>>，供 LLM 改写后原样嵌回。
    """
    if not (text or "").strip():
        return LockExtractResult(editable="", locked_blocks=[])

    lines = text.splitlines()
    out: List[str] = []
    locked: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Markdown 表格：连续 | 行
        if _TABLE_LINE_RE.match(stripped):
            block_lines = [line]
            i += 1
            while i < len(lines) and (
                _TABLE_LINE_RE.match(lines[i].strip()) or not lines[i].strip()
            ):
                # 表内空行结束表
                if not lines[i].strip():
                    # peek：空行后若仍是表则并入
                    if i + 1 < len(lines) and _TABLE_LINE_RE.match(lines[i + 1].strip()):
                        block_lines.append(lines[i])
                        i += 1
                        continue
                    break
                block_lines.append(lines[i])
                i += 1
            idx = len(locked)
            locked.append("\n".join(block_lines))
            out.append(f"<<LOCKED_{idx}>>")
            continue

        # 图片行
        if _IMAGE_RE.search(stripped) or _FIGURE_PLACEHOLDER_RE.match(stripped):
            idx = len(locked)
            locked.append(line)
            out.append(f"<<LOCKED_{idx}>>")
            i += 1
            continue

        out.append(line)
        i += 1

    return LockExtractResult(editable="\n".join(out).strip(), locked_blocks=locked)


def restore_locked_blocks(editable: str, locked_blocks: List[str]) -> str:
    """把 <<LOCKED_n>> 还原为原文块。"""
    text = editable or ""

    def repl(m: re.Match[str]) -> str:
        idx = int(m.group(1))
        if 0 <= idx < len(locked_blocks):
            return locked_blocks[idx]
        return m.group(0)

    # 允许模型把 token 单独成行或嵌在段落中
    restored = _LOCKED_TOKEN_RE.sub(repl, text)
    # 若模型删掉了某些 token，把未使用的锁定块追加到节末（保底）
    used = {int(x) for x in _LOCKED_TOKEN_RE.findall(text)}
    missing = [locked_blocks[i] for i in range(len(locked_blocks)) if i not in used]
    if missing:
        restored = restored.rstrip() + "\n\n" + "\n\n".join(missing)
    return restored.strip()


def find_section(sections: List[DraftSection], heading: str) -> Optional[DraftSection]:
    target = (heading or "").strip().lower()
    for s in sections:
        if s.heading.strip().lower() == target:
            return s
    # 宽松：包含匹配
    for s in sections:
        h = s.heading.strip().lower()
        if target in h or h in target:
            return s
    return None


def replace_section_in_markdown(
    markdown: str,
    heading: str,
    new_section_markdown: str,
) -> str:
    """用新节（可含标题行）替换文档中对应节。"""
    sections = split_markdown_sections(markdown)
    target = find_section(sections, heading)
    if not target:
        raise ValueError(f"找不到章节: {heading}")

    lines = (markdown or "").splitlines()
    new_text = (new_section_markdown or "").strip()
    # 若新稿无标题，补上原标题
    if not _HEADING_RE.match(new_text.splitlines()[0].strip() if new_text else ""):
        hashes = "#" * target.level
        new_text = f"{hashes} {target.heading}\n\n{new_text}".strip()

    new_lines = new_text.splitlines()
    result = lines[: target.start_line] + new_lines + lines[target.end_line :]
    # 节间保一个空行
    return "\n".join(result).strip() + "\n"


def apply_section_overrides(content_markdown: str, overrides: Optional[dict]) -> str:
    """按 heading 依次替换（P0/P2 确认前拼装）。"""
    text = content_markdown or ""
    if not overrides:
        return text
    for heading, body in overrides.items():
        if not heading or body is None:
            continue
        try:
            text = replace_section_in_markdown(text, str(heading), str(body))
        except ValueError:
            continue
    return text


@dataclass
class SectionDiffItem:
    heading: str
    level: int
    status: str  # unchanged | modified | added | removed | polished
    similarity: float
    has_locked_blocks: bool
    locked_count: int
    working_body: str
    base_body: str
    polished: bool = False


def diff_sections(
    base_markdown: str,
    working_markdown: str,
    polished_headings: Optional[List[str]] = None,
) -> List[SectionDiffItem]:
    """相对 base 的分节 diff 元数据。"""
    polished = {(h or "").strip().lower() for h in (polished_headings or [])}
    base_secs = {s.heading.strip().lower(): s for s in split_markdown_sections(base_markdown)}
    work_secs = split_markdown_sections(working_markdown)
    work_keys = {s.heading.strip().lower() for s in work_secs}

    items: List[SectionDiffItem] = []
    for ws in work_secs:
        key = ws.heading.strip().lower()
        bs = base_secs.get(key)
        if not bs:
            status = "added"
            sim = 0.0
            base_body = ""
        else:
            sim = SequenceMatcher(None, bs.body.strip(), ws.body.strip()).ratio()
            status = "unchanged" if sim > 0.98 else "modified"
            base_body = bs.body
        if key in polished:
            status = "polished"
        items.append(
            SectionDiffItem(
                heading=ws.heading,
                level=ws.level,
                status=status,
                similarity=round(sim, 3),
                has_locked_blocks=ws.has_locked_blocks,
                locked_count=ws.locked_count,
                working_body=ws.body,
                base_body=base_body,
                polished=key in polished,
            )
        )

    for key, bs in base_secs.items():
        if key not in work_keys:
            items.append(
                SectionDiffItem(
                    heading=bs.heading,
                    level=bs.level,
                    status="removed",
                    similarity=0.0,
                    has_locked_blocks=bs.has_locked_blocks,
                    locked_count=bs.locked_count,
                    working_body="",
                    base_body=bs.body,
                    polished=False,
                )
            )
    return items


def highlight_line_diff(base: str, working: str) -> List[Dict[str, str]]:
    """
    简易行级 diff，供 UI 高亮。
    每项: {type: equal|insert|delete|replace, text, base_text?}
    """
    a = (base or "").splitlines()
    b = (working or "").splitlines()
    sm = SequenceMatcher(None, a, b)
    rows: List[Dict[str, str]] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for line in b[j1:j2]:
                rows.append({"type": "equal", "text": line})
        elif tag == "insert":
            for line in b[j1:j2]:
                rows.append({"type": "insert", "text": line})
        elif tag == "delete":
            for line in a[i1:i2]:
                rows.append({"type": "delete", "text": line})
        elif tag == "replace":
            for line in a[i1:i2]:
                rows.append({"type": "delete", "text": line})
            for line in b[j1:j2]:
                rows.append({"type": "insert", "text": line})
    return rows
