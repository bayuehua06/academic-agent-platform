"""章节精修：单节改写 + 多轮候选底稿 + 大纲 Seed / Working Facts / 上游摘要。"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from app.services.citation_guard import (
    CITATION_HARD_RULES,
    format_allowed_sources_block,
    sanitize_citations,
)
from app.services.draft_sections import (
    extract_locked_blocks,
    find_section,
    restore_locked_blocks,
    split_markdown_sections,
)
from app.services.llm_client import resolve_model, safe_invoke_chat
from app.services import summarizer as summarizer_module

logger = logging.getLogger(__name__)

_POLISH_SYSTEM = (
    "You are an academic writing assistant polishing ONE section of a paper.\n"
    f"{CITATION_HARD_RULES}\n"
    "Other hard rules:\n"
    "- Output ONLY the revised section body in Markdown (include the heading line).\n"
    "- Preserve every <<LOCKED_n>> token EXACTLY where it appears (figures/tables).\n"
    "- DEFAULT language: academic English unless the instruction says otherwise.\n"
    "- Follow the user instruction closely; keep unchanged parts stable when possible.\n"
    "- OUTLINE SEED (authoritative): named cases, proposal titles, and facts from the "
    "locked outline key_points MUST be preserved. Do NOT invent a conflicting case study "
    "or rename the user's proposals unless the user instruction explicitly asks to change them.\n"
    "- WORKING FACTS and UPSTREAM SUMMARY (when provided) are also binding continuity "
    "constraints—stay consistent with them.\n"
    "- SECTION DIRECTIVES (when provided) come from prior confirmed polish—obey them "
    "unless the user instruction explicitly overrides.\n"
    "- Do NOT add a References list."
)


def format_sources_for_polish(sources: Sequence[Dict[str, Any]], limit: int = 40) -> str:
    return format_allowed_sources_block(sources, limit=limit)


def match_outline_key_points(paper_outline: Any, heading: str) -> str:
    """从锁定大纲中取与 heading 匹配的 key_points（大小写不敏感）。"""
    if not paper_outline or not isinstance(paper_outline, list):
        return ""
    target = (heading or "").strip().lower()
    if not target:
        return ""
    for item in paper_outline:
        if isinstance(item, str):
            continue
        if not isinstance(item, dict):
            continue
        h = (item.get("heading") or "").strip()
        if h.lower() == target:
            return (item.get("key_points") or "").strip()
    # 宽松：子串匹配（大纲标题略短/略长）
    for item in paper_outline:
        if not isinstance(item, dict):
            continue
        h = (item.get("heading") or "").strip()
        hl = h.lower()
        if not hl:
            continue
        if target in hl or hl in target:
            return (item.get("key_points") or "").strip()
    return ""


def outline_seeds_map(paper_outline: Any) -> Dict[str, str]:
    """heading → key_points，供 UI / API 展示。"""
    out: Dict[str, str] = {}
    if not paper_outline or not isinstance(paper_outline, list):
        return out
    for item in paper_outline:
        if not isinstance(item, dict):
            continue
        h = (item.get("heading") or "").strip()
        kp = (item.get("key_points") or "").strip()
        if h and kp:
            out[h] = kp
    return out


def build_upstream_summaries(
    full_markdown: str,
    heading: str,
    *,
    max_chars_per: int = 420,
    max_sections: int = 5,
) -> str:
    """取当前节之前的上游节正文摘要（截断），供跨节连续性。"""
    sections = split_markdown_sections(full_markdown)
    idx = None
    for i, sec in enumerate(sections):
        if sec.heading.strip().lower() == heading.strip().lower():
            idx = i
            break
    if idx is None or idx == 0:
        return ""
    upstream = sections[max(0, idx - max_sections) : idx]
    chunks: List[str] = []
    for sec in upstream:
        body = (sec.body or "").strip().replace("\n", " ")
        if len(body) > max_chars_per:
            body = body[: max_chars_per - 1] + "…"
        chunks.append(f"### {sec.heading}\n{body or '(empty)'}")
    return "\n\n".join(chunks)


def headings_after(full_markdown: str, heading: str) -> List[str]:
    """当前节之后的下游 heading（不含 References）。"""
    sections = split_markdown_sections(full_markdown)
    found = False
    out: List[str] = []
    skip = {"references", "reference", "参考文献"}
    for sec in sections:
        if found:
            if sec.heading.strip().lower() not in skip:
                out.append(sec.heading)
        if sec.heading.strip().lower() == heading.strip().lower():
            found = True
    return out


def polish_section_markdown(
    *,
    full_markdown: str,
    heading: str,
    instruction: str,
    sources: Sequence[Dict[str, Any]],
    base_markdown: Optional[str] = None,
    prior_instructions: Optional[List[str]] = None,
    outline_key_points: str = "",
    working_facts: str = "",
    upstream_summaries: str = "",
    section_directives: str = "",
) -> Dict[str, Any]:
    """
    精修单节。

    Args:
        full_markdown: 工作区当前整篇（已含 overrides / 可选编辑区替换）
        base_markdown: 多轮时以上一预览为底；若提供则优先作为本节输入
        prior_instructions: 近几轮指令（可选上下文）
        outline_key_points / working_facts / upstream_summaries / section_directives: 硬约束

    Returns:
        dict: preview_markdown, mode (llm|passthrough), model, locked_count, heading
    """
    sections = split_markdown_sections(full_markdown)
    section = find_section(sections, heading)
    if not section and not (base_markdown and base_markdown.strip()):
        raise ValueError(f"找不到章节: {heading}")

    # References 节不允许精修
    ref_heading = (section.heading if section else heading).strip().lower()
    if ref_heading in {"references", "reference", "参考文献"}:
        raise ValueError("References 节请在确认版本时由系统重建，不能手工精修")

    # 多轮：以候选预览为底
    if base_markdown and base_markdown.strip():
        base_secs = split_markdown_sections(base_markdown.strip())
        base_sec = find_section(base_secs, heading) or (base_secs[0] if base_secs else None)
        if base_sec:
            level = base_sec.level
            body = base_sec.body
            resolved_heading = base_sec.heading
        else:
            # 整段当作正文（可能只有标题行）
            level = section.level if section else 2
            lines = base_markdown.strip().splitlines()
            if lines and lines[0].strip().startswith("#"):
                body = "\n".join(lines[1:]).strip()
            else:
                body = base_markdown.strip()
            resolved_heading = section.heading if section else heading
    else:
        assert section is not None
        level = section.level
        body = section.body
        resolved_heading = section.heading

    extracted = extract_locked_blocks(body)
    hashes = "#" * level
    heading_line = f"{hashes} {resolved_heading}"

    if not summarizer_module.has_openai_key():
        restored = restore_locked_blocks(extracted.editable, extracted.locked_blocks)
        preview = f"{heading_line}\n\n{restored}\n" if restored else f"{heading_line}\n"
        return {
            "heading": resolved_heading,
            "preview_markdown": preview,
            "mode": "passthrough",
            "model": None,
            "locked_count": len(extracted.locked_blocks),
            "openai_configured": False,
        }

    prior_block = ""
    if prior_instructions:
        cleaned = [p.strip() for p in prior_instructions if p and str(p).strip()]
        if cleaned:
            prior_block = "Prior polish turns in this thread:\n" + "\n".join(
                f"- {p}" for p in cleaned[-5:]
            )

    seed_block = (
        f"OUTLINE SEED (authoritative — from locked paper outline key_points):\n"
        f"{outline_key_points.strip() or '(none for this section)'}\n"
    )
    facts_block = (
        f"WORKING FACTS (binding continuity constraints for this workspace):\n"
        f"{working_facts.strip() or '(none yet)'}\n"
    )
    upstream_block = (
        f"UPSTREAM SECTIONS (already accepted / current workspace — stay consistent):\n"
        f"{upstream_summaries.strip() or '(none — first section or empty)'}\n"
    )
    directives_block = (
        f"SECTION DIRECTIVES (persisted from prior confirmed polish — obey):\n"
        f"{section_directives.strip() or '(none)'}\n"
    )

    parts = [
        f"Section heading: {resolved_heading}",
        f"User instruction (this turn):\n{instruction.strip()}",
    ]
    if prior_block:
        parts.append(prior_block)
    parts.extend(
        [
            seed_block.strip(),
            facts_block.strip(),
            directives_block.strip(),
            upstream_block.strip(),
            format_sources_for_polish(sources),
            f"Current section (preserve <<LOCKED_n>> tokens):\n{heading_line}\n\n{extracted.editable}",
        ]
    )
    user = "\n\n".join(parts) + "\n"

    model = resolve_model("default")
    raw = safe_invoke_chat(
        _POLISH_SYSTEM,
        user,
        temperature=0.35,
        max_input=14000,
        max_tokens=4000,
        purpose="default",
    )
    if not raw:
        restored = restore_locked_blocks(extracted.editable, extracted.locked_blocks)
        preview = f"{heading_line}\n\n{restored}\n" if restored else f"{heading_line}\n"
        return {
            "heading": resolved_heading,
            "preview_markdown": preview,
            "mode": "passthrough",
            "model": model,
            "locked_count": len(extracted.locked_blocks),
            "openai_configured": True,
            "error": "llm_failed",
        }

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("markdown"):
            cleaned = cleaned[8:].lstrip()

    lines = cleaned.splitlines()
    if lines and lines[0].strip().startswith("#"):
        out_heading_line = lines[0].strip()
        out_body = "\n".join(lines[1:]).strip()
    else:
        out_heading_line = heading_line
        out_body = cleaned

    restored_body = restore_locked_blocks(out_body, extracted.locked_blocks)
    restored_body, stripped = sanitize_citations(restored_body, sources)
    if stripped:
        logger.warning("精修剔除编造引用: %s", stripped[:8])
    preview = f"{out_heading_line}\n\n{restored_body}\n" if restored_body else f"{out_heading_line}\n"

    return {
        "heading": resolved_heading,
        "preview_markdown": preview,
        "mode": "llm",
        "model": model,
        "locked_count": len(extracted.locked_blocks),
        "openai_configured": True,
        "stripped_citations": stripped,
    }


def build_pending_directive(heading: str, instruction: str) -> Dict[str, str]:
    """工作区暂存的章节指令（确认时再持久化，P3）。"""
    text = instruction.strip()
    return {
        "outline_heading": heading,
        "directive_text": f"[Section: {heading}] {text}",
        "instruction": text,
    }
