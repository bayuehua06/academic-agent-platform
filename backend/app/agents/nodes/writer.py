"""Node 3: APA Writer — 约束抽取 + 分节写作（Writer 模型）+ 轻量校验补写。"""

from __future__ import annotations

import logging
from typing import List, Optional

from app.agents.state import AcademicAgentState, LiteratureSource, OutlineSection
from app.services import summarizer as summarizer_module
from app.services.citation_guard import (
    CITATION_HARD_RULES,
    format_intext_citation,
    sanitize_citations,
    verify_citations,
)
from app.services.evidence_cards import format_allowed_sources_with_evidence
from app.services.llm_client import resolve_model, safe_invoke_chat
from app.services.pandoc_service import strip_references_section
from app.services.structure_guard import (
    force_section_heading,
    format_table_seed_hint,
    rebuild_draft_to_outline,
    strip_nested_outline_headings,
)
from app.services.writing_constraints import (
    WritingConstraints,
    bind_must_apply_documents,
    count_words,
    extract_writing_constraints,
    format_must_apply_block,
    parse_word_target,
    verify_draft_against_constraints,
)
from app.services.literature_assignments import filter_sources_for_heading

logger = logging.getLogger(__name__)

# re-export for tests that import from writer
allocate_section_words = None  # set below after def


_SECTION_SYSTEM = (
    "You are an academic writing assistant. Write ONE section of a scholarly paper "
    "in Markdown (APA 7th in-text citations only unless HARD CONSTRAINTS say otherwise).\n"
    f"{CITATION_HARD_RULES}\n"
    "Other hard rules (priority: structure & Assessment/Specific over fluency):\n"
    "- LANGUAGE (HARD): Output MUST be academic English for ALL prose AND all Markdown "
    "table headers/cells. Chinese (or other languages) appearing in OUTLINE SEED / tables "
    "are draft notes only — translate and rewrite into English; NEVER leave Chinese "
    "draft text in the final section unless HARD CONSTRAINTS explicitly require Chinese.\n"
    "- Output ONLY this section: the given heading line, then body.\n"
    "- Do NOT write other sections, a title page, or a References list.\n"
    "- Do NOT change the outline heading text or invent sibling sections.\n"
    "- Do NOT emit child/sibling outline headings inside this section; other sections "
    "are written separately.\n"
    "- STRUCTURE FIDELITY: If OUTLINE SEED contains a Markdown table framework, you MUST "
    "keep an isomorphic Markdown pipe table (same columns); fill/rewrite cells in English. "
    "Never replace a required table with prose-only paragraphs.\n"
    "- Obey HARD CONSTRAINTS completely. Assessment (grading) and Specific requirements "
    "are co-equal and binding. MUST APPLY documents override soft background notes.\n"
    "- OUTLINE SEED (authoritative for facts/names): named cases, proposal titles, and "
    "given facts MUST be used (in English). Do NOT invent a conflicting case study or "
    "rename the user's proposals.\n"
    "- Obey SECTION DIRECTIVES and CONFIRMED FACTS when provided (from prior polish).\n"
    "- Hit the target word count for THIS section (±15%) WITHOUT sacrificing tables, "
    "headings, or hard requirements. Prefer cutting fluff over dropping structure.\n"
    "- Stay consistent with the previous-section summary when provided."
)


def _normalize_outline(paper_outline: list) -> List[OutlineSection]:
    out: List[OutlineSection] = []
    for item in paper_outline:
        if isinstance(item, str):
            out.append({"level": 1, "heading": item, "key_points": ""})
        elif isinstance(item, dict):
            heading = (item.get("heading") or "").strip()
            if not heading:
                continue
            out.append(
                {
                    "level": int(item.get("level") or 1),
                    "heading": heading,
                    "key_points": (item.get("key_points") or "").strip(),
                }
            )
    return out


def allocate_section_words(
    sections: List[OutlineSection],
    target_min: int,
    target_max: int,
) -> List[int]:
    """按节分配目标词数：leaf 权重更高；引言/结论略少。"""
    n = len(sections)
    if n == 0:
        return []
    mid = (target_min + target_max) // 2
    weights: List[float] = []
    for i, sec in enumerate(sections):
        level = int(sec.get("level") or 1)
        heading = (sec.get("heading") or "").lower()
        is_leaf = i == n - 1 or int(sections[i + 1].get("level") or 1) <= level
        w = 1.4 if is_leaf else 0.6
        if any(
            k in heading
            for k in ("introduction", "引言", "背景", "conclusion", "结论", "摘要", "abstract")
        ):
            w *= 0.85
        if (sec.get("key_points") or "").strip():
            w *= 1.15
        weights.append(max(0.4, w))

    total_w = sum(weights) or float(n)
    raw = [mid * (w / total_w) for w in weights]
    floor = max(150, min(280, mid // max(n * 2, 1)))
    capped = [max(floor, int(round(x))) for x in raw]
    diff = mid - sum(capped)
    i = 0
    while diff != 0 and n > 0 and abs(diff) < mid:
        idx = i % n
        if diff > 0:
            capped[idx] += 1
            diff -= 1
        elif capped[idx] > floor:
            capped[idx] -= 1
            diff += 1
        else:
            i += 1
            if i > n * 3:
                break
            continue
        i += 1
    return capped


def _heading_md(level: int, title: str) -> str:
    return f"{'#' * max(1, min(int(level or 1), 6))} {title}"


def _section_paragraph(
    section: OutlineSection,
    sources: List[LiteratureSource],
    index: int,
) -> str:
    title = section.get("heading") or f"Section {index + 1}"
    level = int(section.get("level") or 1)
    key_points = (section.get("key_points") or "").strip()
    heading = _heading_md(level, title)
    focus = key_points[:400] if key_points else title

    if not sources:
        return (
            f"{heading}\n\n"
            f"This section addresses {focus}. Further empirical support should be "
            f"integrated as sources become available.\n"
        )

    src = sources[index % len(sources)]
    cite = format_intext_citation(src.get("authors") or [], src.get("year") or "")
    topic = src.get("title", "prior research")
    points_line = f" Section focus: {key_points[:300]}." if key_points else ""
    return (
        f"{heading}\n\n"
        f"Recent scholarship on this topic highlights key debates surrounding "
        f"*{topic}* {cite}.{points_line} Building on these findings, the present "
        f"discussion synthesizes methodological insights and situates them within "
        f"the assessment framework.\n"
    )


def _format_sources_for_prompt(
    sources: List[LiteratureSource],
    *,
    heading: str,
    key_points: str,
    limit: int = 40,
) -> str:
    """允许文献块（空库时明确禁止任何文内引用）。"""
    return format_allowed_sources_with_evidence(
        sources,
        heading=heading,
        key_points=key_points,
        limit=limit,
    )


def _ensure_heading(body: str, section: OutlineSection) -> str:
    """强制使用大纲标题（剥离开头错误标题行）。"""
    return force_section_heading(
        body,
        heading=section.get("heading") or "Section",
        level=int(section.get("level") or 1),
    )


def _section_max_tokens(word_target: int) -> int:
    return max(800, min(8000, int(word_target * 2.2) + 400))


def _prev_summary(text: str, limit: int = 500) -> str:
    body = (text or "").strip()
    if not body:
        return "(none — this is the first section)"
    return body[-limit:]


def _directives_for_heading(directives: list, heading: str) -> str:
    """按 heading 过滤 active 指令文本。"""
    target = (heading or "").strip().lower()
    lines: List[str] = []
    for item in directives or []:
        if not isinstance(item, dict):
            continue
        h = (item.get("outline_heading") or "").strip()
        text = (item.get("directive_text") or "").strip()
        if not h or not text:
            continue
        hl = h.lower()
        if hl == target or target in hl or hl in target:
            lines.append(f"- {text}")
    return "\n".join(lines)


def _write_section_llm(
    *,
    section: OutlineSection,
    word_target: int,
    constraints: WritingConstraints,
    assessment: str,
    backgrounds: str,
    sources: list,
    section_index: int,
    section_count: int,
    previous_summary: str,
    section_directives: str = "",
    confirmed_facts: str = "",
    must_apply_block: str = "",
) -> Optional[str]:
    heading = section.get("heading") or f"Section {section_index + 1}"
    level = int(section.get("level") or 1)
    key_points = (section.get("key_points") or "").strip()
    lo, hi = constraints.word_target()
    table_hint = format_table_seed_hint(key_points)
    parts = [
        constraints.to_prompt_block(),
    ]
    if must_apply_block.strip():
        parts.append(must_apply_block.strip())
    parts.extend(
        [
            f"This is section {section_index + 1} of {section_count}.",
            f"Overall paper length target: {lo}-{hi} English words.",
            f"TARGET FOR THIS SECTION ONLY: about {word_target} English words "
            f"(acceptable {int(word_target * 0.85)}-{int(word_target * 1.15)}). "
            "Do not pad past the overall max.",
            f"Section heading (Markdown level {level}): {_heading_md(level, heading)}",
            "OUTLINE SEED / key_points (authoritative facts — must use; write the section "
            "in English even if the seed contains Chinese draft notes):\n"
            f"{key_points or '(none)'}",
        ]
    )
    if table_hint:
        parts.append(table_hint.strip())
    parts.extend(
        [
            f"CONFIRMED FACTS (from prior polish — stay consistent):\n"
            f"{confirmed_facts.strip() or '(none)'}",
            f"SECTION DIRECTIVES (from prior polish — obey when regenerating this section):\n"
            f"{section_directives.strip() or '(none)'}",
            f"Previous section ending (for continuity):\n{previous_summary}",
            "Assessment / grading (HARD — already in HARD CONSTRAINTS; excerpt for focus):\n"
            f"{assessment[:2500] or '(none)'}",
            f"Background notes (SOFT reference only):\n{backgrounds[:1800] or '(none)'}",
            _format_sources_for_prompt(
                sources,
                heading=heading,
                key_points=key_points,
            ),
        ]
    )
    user = "\n\n".join(parts) + "\n"
    return safe_invoke_chat(
        _SECTION_SYSTEM,
        user,
        temperature=0.45,
        max_input=18000,
        max_tokens=_section_max_tokens(word_target),
        purpose="writer",
    )


def _compress_section_if_long(
    body: str,
    *,
    section: OutlineSection,
    word_target: int,
    constraints: WritingConstraints,
    sources: list,
) -> str:
    """偏长则压缩；保留表与标题。"""
    words = count_words(body)
    if words <= int(word_target * 1.20):
        return body
    kp = (section.get("key_points") or "").strip()
    table_hint = format_table_seed_hint(kp)
    user_prompt = (
        f"{constraints.to_prompt_block()}\n\n"
        f"{table_hint}\n"
        f"Current section (~{words} words) must shrink toward ~{word_target} words "
        f"(acceptable up to {int(word_target * 1.15)}).\n\n"
        f"{_format_sources_for_prompt(sources, heading=section.get('heading') or '', key_points=kp)}\n\n"
        f"Section to compress:\n{body}\n"
    )
    max_input = 14000
    truncated = user_prompt[:max_input]
    # #region agent log
    try:
        import json
        import time
        _dbg = {
            "sessionId": "4a542e",
            "runId": "pre-fix",
            "hypothesisId": "H1",
            "location": "writer.py:_compress_section_if_long",
            "message": "compress prompt truncation check",
            "data": {
                "heading": (section.get("heading") or "")[:120],
                "word_target": word_target,
                "body_words": words,
                "body_chars": len(body or ""),
                "body_head": (body or "")[:160],
                "prompt_chars": len(user_prompt),
                "max_input": max_input,
                "truncated": len(user_prompt) > max_input,
                "marker_in_full": "Section to compress:" in user_prompt,
                "marker_in_trunc": "Section to compress:" in truncated,
                "body_tail_in_trunc": (body or "")[-80:] in truncated if body else False,
                "trunc_tail": truncated[-200:],
                "sources_n": len(sources or []),
            },
            "timestamp": int(time.time() * 1000),
        }
        with open(
            "/Users/songchen/github/academic-agent-platform/.cursor/debug-4a542e.log",
            "a",
            encoding="utf-8",
        ) as _f:
            _f.write(json.dumps(_dbg, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # #endregion
    compressed = safe_invoke_chat(
        (
            "Compress the academic Markdown section below. Keep the same heading. "
            f"{CITATION_HARD_RULES}\n"
            "Obey HARD CONSTRAINTS. MUST preserve Markdown tables and column structure. "
            "Cut fluff and repetition; do not drop rubric must-includes. Output the full section."
        ),
        user_prompt,
        temperature=0.3,
        max_input=max_input,
        max_tokens=_section_max_tokens(word_target),
        purpose="writer",
    )
    # #region agent log
    try:
        import json
        import time
        _meta = False
        _low = (compressed or "").lower()
        if compressed and (
            "was not included" in _low
            or "please provide the section" in _low
            or "section to be compressed" in _low
        ):
            _meta = True
        _dbg2 = {
            "sessionId": "4a542e",
            "runId": "pre-fix",
            "hypothesisId": "H3",
            "location": "writer.py:_compress_section_if_long:after",
            "message": "compress LLM result",
            "data": {
                "heading": (section.get("heading") or "")[:120],
                "in_words": words,
                "out_words": count_words(compressed or ""),
                "out_chars": len(compressed or ""),
                "out_head": (compressed or "")[:220],
                "looks_like_meta": _meta,
                "will_accept": bool(compressed and count_words(compressed) < words),
            },
            "timestamp": int(time.time() * 1000),
        }
        with open(
            "/Users/songchen/github/academic-agent-platform/.cursor/debug-4a542e.log",
            "a",
            encoding="utf-8",
        ) as _f:
            _f.write(json.dumps(_dbg2, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # #endregion
    if compressed and count_words(compressed) < words:
        cleaned, _ = sanitize_citations(_ensure_heading(compressed, section), sources)
        return cleaned
    return body


def _expand_section_if_short(
    body: str,
    *,
    section: OutlineSection,
    word_target: int,
    constraints: WritingConstraints,
    sources: list,
) -> str:
    """偏短则扩写；扩写同样带上完整 HARD CONSTRAINTS。"""
    words = count_words(body)
    if words >= int(word_target * 0.75):
        return body
    need = max(120, word_target - words)
    kp = (section.get("key_points") or "").strip()
    table_hint = format_table_seed_hint(kp)
    user_prompt = (
        f"{constraints.to_prompt_block()}\n\n"
        f"{table_hint}\n"
        f"Current section (~{words} words) must grow by about {need} words "
        f"toward ~{word_target} words without dropping tables.\n\n"
        f"{_format_sources_for_prompt(sources, heading=section.get('heading') or '', key_points=kp)}\n\n"
        f"Section to expand:\n{body}\n"
    )
    max_input = 14000
    # #region agent log
    try:
        import json
        import time
        _dbg = {
            "sessionId": "4a542e",
            "runId": "pre-fix",
            "hypothesisId": "H5",
            "location": "writer.py:_expand_section_if_short",
            "message": "expand prompt truncation check",
            "data": {
                "heading": (section.get("heading") or "")[:120],
                "body_words": words,
                "prompt_chars": len(user_prompt),
                "truncated": len(user_prompt) > max_input,
                "marker_in_trunc": "Section to expand:" in user_prompt[:max_input],
            },
            "timestamp": int(time.time() * 1000),
        }
        with open(
            "/Users/songchen/github/academic-agent-platform/.cursor/debug-4a542e.log",
            "a",
            encoding="utf-8",
        ) as _f:
            _f.write(json.dumps(_dbg, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # #endregion
    expand = safe_invoke_chat(
        (
            "Expand the academic Markdown section below. Keep the same heading. "
            f"{CITATION_HARD_RULES}\n"
            "Obey HARD CONSTRAINTS. Preserve any Markdown tables. LANGUAGE: academic English "
            "only (translate any Chinese draft text in tables/prose). "
            "Add substantive analysis; cite ONLY "
            "ALLOWED SOURCES (or use zero citations if NONE). Output the full section."
        ),
        user_prompt,
        temperature=0.4,
        max_input=max_input,
        max_tokens=_section_max_tokens(word_target),
        purpose="writer",
    )
    if expand and count_words(expand) > words:
        cleaned, _removed = sanitize_citations(_ensure_heading(expand, section), sources)
        return cleaned
    return body


def _repair_draft_if_needed(
    draft: str,
    *,
    constraints: WritingConstraints,
    sources: list,
    verification: dict,
    paper_outline: Optional[list] = None,
    must_apply_block: str = "",
) -> str:
    """对照 checklist / 字数 / 结构做一轮补写或压短；事后硬锁回大纲骨架。"""
    if verification.get("ok"):
        return draft
    issues = list(verification.get("issues") or [])
    structure = verification.get("structure") or {}
    missing_tables = structure.get("missing_tables") or []
    missing_headings = structure.get("missing_headings") or []
    sections = [
        item
        for item in (paper_outline or [])
        if isinstance(item, dict) and (item.get("heading") or "").strip()
    ]
    locked_headings = [
        f"{'#' * max(1, min(int(item.get('level') or 1), 6))} {(item.get('heading') or '').strip()}"
        for item in sections
    ]
    structure_focus = ""
    if missing_tables:
        structure_focus += (
            "CRITICAL STRUCTURE FIX: Restore Markdown tables for these sections from "
            f"OUTLINE SEED: {', '.join(missing_tables)}. Same columns/headers required.\n"
        )
    if missing_headings:
        structure_focus += (
            "CRITICAL: These locked outline headings were missing and MUST appear "
            f"exactly: {', '.join(missing_headings)}.\n"
        )
    high = any("too high" in (i or "").lower() for i in issues)
    outline_text = "\n".join(
        f"{(item.get('heading') or '').strip()}: {(item.get('key_points') or '').strip()}"
        for item in sections
    )
    locked_block = (
        "LOCKED OUTLINE HEADINGS (output EXACTLY these headings in this order; "
        "do NOT rename, merge, drop, or invent sibling sections; "
        "do NOT add a title like Academic Draft):\n"
        + "\n".join(f"- {h}" for h in locked_headings)
        + "\n"
    )
    repaired = safe_invoke_chat(
        (
            "You revise an academic Markdown draft to satisfy unmet HARD CONSTRAINTS "
            "and OUTLINE STRUCTURE. "
            f"{CITATION_HARD_RULES}\n"
            "STRUCTURE LOCK: Keep the exact locked outline headings and order. "
            "Never rename/merge/drop sections or invent new ones. "
            "Preserve or restore required Markdown tables. "
            "Cite ONLY ALLOWED SOURCES (or zero citations if NONE). "
            "LANGUAGE: academic English for ALL prose and table cells — translate any "
            "Chinese draft notes; do not leave Chinese in the output unless HARD CONSTRAINTS "
            "explicitly require Chinese. "
            "Do not add a References list. Output the full revised Markdown draft."
        ),
        (
            f"{constraints.to_prompt_block()}\n\n"
            f"{must_apply_block}\n\n"
            f"{locked_block}\n"
            f"{structure_focus}"
            f"Unmet issues:\n- " + "\n- ".join(issues) + "\n\n"
            + (
                "Prefer COMPRESSING length while keeping tables and hard requirements.\n\n"
                if high
                else ""
            )
            + f"{_format_sources_for_prompt(sources, heading='Full Draft', key_points=outline_text)}\n\n"
            f"Current draft:\n{draft[:24000]}\n"
        ),
        temperature=0.35,
        max_input=28000,
        max_tokens=12000,
        purpose="writer",
    )
    if not repaired:
        logger.warning("Writer 成稿补写未采用（空返回）；仍硬锁大纲骨架")
        return rebuild_draft_to_outline(draft, sections)
    # 过短才拒绝；允许压缩后变短
    if count_words(repaired) < int(count_words(draft) * 0.55) and not high:
        logger.warning("Writer 成稿补写未采用（过短）；仍硬锁大纲骨架")
        return rebuild_draft_to_outline(draft, sections)
    logger.info("Writer 成稿补写完成；硬锁回大纲骨架")
    cleaned, _ = sanitize_citations(repaired.strip() + "\n", sources)
    return rebuild_draft_to_outline(cleaned, sections)


def _write_with_llm(state: AcademicAgentState, paper_outline: list, sources: list) -> tuple[Optional[str], WritingConstraints, dict]:
    """按章写作；返回 (draft, constraints, verification)。"""
    sections = _normalize_outline(paper_outline)
    empty_c = WritingConstraints()
    if not sections:
        return None, empty_c, {"ok": False, "issues": ["empty outline"]}

    assessment = (
        (state.get("assessment_summary") or "").strip()
        or (state.get("assessment_requirements") or "").strip()
    )
    specific = (state.get("specific_requirements") or "").strip()
    backgrounds = state.get("background_summaries") or []
    bg = "\n\n".join(b.strip() for b in backgrounds if b and b.strip())[:3000]

    constraints = extract_writing_constraints(specific=specific, assessment=assessment)
    target_min, target_max = constraints.word_target()
    budgets = allocate_section_words(sections, target_min, target_max)

    available_docs = list(state.get("available_documents") or [])
    matched_apply, unmatched_apply = bind_must_apply_documents(
        constraints.must_apply_documents, available_docs
    )
    must_apply_block = format_must_apply_block(matched_apply)
    if unmatched_apply:
        logger.warning("必须套用文档未匹配到源文档: %s", unmatched_apply)

    logger.info(
        "Writer model=%s constraints_source=%s 字数=%s-%s 分节=%s checklist=%s "
        "must_apply_matched=%s unmatched=%s",
        resolve_model("writer"),
        constraints.source,
        target_min,
        target_max,
        budgets,
        len(constraints.checklist),
        len(matched_apply),
        unmatched_apply,
    )

    parts: List[str] = []
    ok_sections = 0
    prev = ""
    all_directives = list(state.get("section_directives") or [])
    confirmed_facts = (state.get("confirmed_facts") or "").strip()
    outline_headings = [s.get("heading") or "" for s in sections]
    for i, section in enumerate(sections):
        heading = section.get("heading") or f"Section {i + 1}"
        section_sources = filter_sources_for_heading(sources, heading)
        raw = _write_section_llm(
            section=section,
            word_target=budgets[i],
            constraints=constraints,
            assessment=assessment,
            backgrounds=bg,
            sources=section_sources,
            section_index=i,
            section_count=len(sections),
            previous_summary=_prev_summary(prev),
            section_directives=_directives_for_heading(all_directives, heading),
            confirmed_facts=confirmed_facts,
            must_apply_block=must_apply_block,
        )
        if not raw:
            logger.warning("Writer 第 %s 节失败，用模板段落占位", i + 1)
            body = _section_paragraph(section, section_sources, i)
            parts.append(body)
            prev = body
            continue
        body = _ensure_heading(raw, section)
        body = _expand_section_if_short(
            body,
            section=section,
            word_target=budgets[i],
            constraints=constraints,
            sources=section_sources,
        )
        # #region agent log
        try:
            import json
            import time
            from app.services.writing_constraints import count_words as _cw
            _before = body
            _bw = _cw(body)
            _need_c = _bw > int(budgets[i] * 1.20)
            if _need_c or "background" in heading.lower():
                with open(
                    "/Users/songchen/github/academic-agent-platform/.cursor/debug-4a542e.log",
                    "a",
                    encoding="utf-8",
                ) as _f:
                    _f.write(
                        json.dumps(
                            {
                                "sessionId": "4a542e",
                                "runId": "pre-fix",
                                "hypothesisId": "H2",
                                "location": "writer.py:write_loop_pre_compress",
                                "message": "section before compress",
                                "data": {
                                    "heading": heading[:120],
                                    "budget": budgets[i],
                                    "body_words": _bw,
                                    "will_compress": _need_c,
                                    "body_chars": len(body or ""),
                                    "sources_n": len(section_sources or []),
                                },
                                "timestamp": int(time.time() * 1000),
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
        except Exception:
            pass
        # #endregion
        body = _compress_section_if_long(
            body,
            section=section,
            word_target=budgets[i],
            constraints=constraints,
            sources=section_sources,
        )
        body = _ensure_heading(body, section)
        # 父节若误写出子大纲标题，先剥掉，避免与后续专写节拼接重复
        body_lines = body.splitlines()
        if body_lines:
            head_line, rest = body_lines[0], "\n".join(body_lines[1:])
            rest = strip_nested_outline_headings(
                rest, outline_headings, keep_heading=heading
            )
            body = f"{head_line}\n\n{rest}\n" if rest else f"{head_line}\n"
        body, removed = sanitize_citations(body, section_sources)
        if removed:
            logger.warning(
                "Writer 第 %s 节剔除编造引用: %s",
                i + 1,
                removed[:8],
            )
        parts.append(body)
        prev = body
        ok_sections += 1

    if ok_sections == 0:
        return None, constraints, {"ok": False, "issues": ["all sections failed"]}

    draft = "\n".join(parts).strip() + "\n"
    # 分节拼接后再硬锁一次，去掉模型夹带的额外标题
    draft = rebuild_draft_to_outline(draft, sections)
    draft, removed_all = sanitize_citations(draft, sources)
    draft = strip_references_section(draft).strip() + "\n"
    draft = rebuild_draft_to_outline(draft, sections)
    verification = verify_draft_against_constraints(
        draft, constraints, paper_outline=sections
    )
    if unmatched_apply:
        issues = list(verification.get("issues") or [])
        issues.append(
            "Must-apply documents not found in project sources (warned): "
            + "; ".join(unmatched_apply[:8])
        )
        verification["issues"] = issues
        # 仅警告，不因未匹配阻断 ok（结构/字数/must_include 仍决定 ok）
        verification["must_apply_unmatched"] = unmatched_apply
    verification["must_apply_matched"] = [
        {"name": m.get("name"), "title": m.get("title"), "role": m.get("role")}
        for m in matched_apply
    ]

    cite_check = verify_citations(draft, sources)
    if cite_check.get("hallucinated"):
        issues = list(verification.get("issues") or [])
        issues.append(
            "Removed or still-present citations not in library: "
            + "; ".join(cite_check["hallucinated"][:10])
        )
        verification["issues"] = issues
        verification["ok"] = False
        verification["citation_ok"] = False
        verification["hallucinated_citations"] = cite_check["hallucinated"]
        draft, _ = sanitize_citations(draft, sources)
    else:
        verification["citation_ok"] = True
        verification["hallucinated_citations"] = []
    if removed_all:
        verification["stripped_citations"] = removed_all

    # 结构/字数/must_include 失败才 repair（未匹配文档仅警告）
    need_repair = bool(
        verification.get("missing_must_include")
        or (verification.get("structure") or {}).get("issues")
        or any(
            "word count" in (i or "").lower() for i in (verification.get("issues") or [])
        )
    )
    auto_repair = bool(state.get("writer_auto_repair"))
    verification["repair_needed"] = need_repair
    verification["repair_skipped"] = bool(need_repair and not auto_repair)
    if need_repair and auto_repair:
        draft = _repair_draft_if_needed(
            draft,
            constraints=constraints,
            sources=sources,
            verification=verification,
            paper_outline=sections,
            must_apply_block=must_apply_block,
        )
        draft, _ = sanitize_citations(draft, sources)
        verification = verify_draft_against_constraints(
            draft, constraints, paper_outline=sections
        )
        cite_check = verify_citations(draft, sources)
        verification["citation_ok"] = cite_check.get("ok", True)
        verification["hallucinated_citations"] = cite_check.get("hallucinated") or []
        verification["repair_needed"] = False
        verification["repaired"] = True
        if unmatched_apply:
            verification["must_apply_unmatched"] = unmatched_apply
        verification["must_apply_matched"] = [
            {"name": m.get("name"), "title": m.get("title"), "role": m.get("role")}
            for m in matched_apply
        ]
    elif need_repair:
        logger.info("Writer 校验未过且 auto_repair=False，跳过自动补写，交由用户确认")

    logger.info(
        "Writer 完成：words≈%s target=%s-%s ok=%s citation_ok=%s issues=%s",
        verification.get("word_count"),
        target_min,
        target_max,
        verification.get("ok"),
        verification.get("citation_ok"),
        verification.get("issues"),
    )
    return draft, constraints, verification


def _write_template(state: AcademicAgentState, paper_outline: list, sources: list) -> str:
    requirements = (
        (state.get("assessment_summary") or "").strip()
        or (state.get("assessment_requirements") or "").strip()
    )
    specific = (state.get("specific_requirements") or "").strip()
    keywords = state.get("keywords") or []
    target_min, target_max = parse_word_target(specific, requirements)

    intro_extra = ""
    if requirements:
        intro_extra += f"\n\nAssessment focus: {requirements[:500]}\n"
    if specific:
        intro_extra += f"\nSpecific requirements: {specific[:1200]}\n"
    intro_extra += (
        f"\n*Note: template mode cannot fully honor length/constraints "
        f"(target {target_min}-{target_max} words); set OPENAI_API_KEY.*\n"
    )

    parts = [
        f"*Keywords: {', '.join(keywords)}*\n",
        intro_extra,
    ]
    for i, section in enumerate(_normalize_outline(paper_outline)):
        heading = section.get("heading") or f"Section {i + 1}"
        section_sources = filter_sources_for_heading(sources, heading)
        parts.append(_section_paragraph(section, section_sources, i))
    draft = "\n".join(parts).strip() + "\n"
    return rebuild_draft_to_outline(draft, paper_outline)


def write_apa_draft(state: AcademicAgentState) -> AcademicAgentState:
    """APA Writer：约束抽取 → 分节（Writer 模型）→ 校验补写。"""
    logger.info("Agent step: write_apa_draft (project=%s)", state.get("project_id"))

    paper_outline = state.get("paper_outline") or []
    if not paper_outline:
        paper_outline = [
            {"level": 1, "heading": h, "key_points": ""}
            for h in (state.get("outline") or ["Introduction", "Discussion", "Conclusion"])
        ]

    sources = state.get("sources") or []
    mode = "template"
    draft = ""
    constraints = WritingConstraints(
        raw_specific=(state.get("specific_requirements") or ""),
        raw_assessment_excerpt=(
            (state.get("assessment_summary") or "")
            or (state.get("assessment_requirements") or "")
        )[:2000],
    )
    word_lo, word_hi = constraints.word_target()
    verification: dict = {}

    if summarizer_module.has_openai_key():
        llm_draft, constraints, verification = _write_with_llm(
            state, paper_outline, sources
        )
        word_lo, word_hi = constraints.word_target()
        if llm_draft:
            draft = llm_draft.strip() + "\n"
            mode = "llm"
        else:
            logger.warning("write_apa_draft LLM 失败，回退模板")

    if not draft:
        constraints = extract_writing_constraints(
            specific=(state.get("specific_requirements") or ""),
            assessment=(state.get("assessment_summary") or "")
            or (state.get("assessment_requirements") or ""),
        )
        word_lo, word_hi = constraints.word_target()
        draft = _write_template(state, paper_outline, sources)
        mode = "template"
        verification = verify_draft_against_constraints(draft, constraints)

    return {
        **state,
        "draft_markdown": draft,
        "writer_mode": mode,
        "writer_model": resolve_model("writer") if mode == "llm" else None,
        "writer_word_count": count_words(draft),
        "writer_word_target": {"min": word_lo, "max": word_hi},
        "writer_constraints": constraints.as_public_dict(),
        "writer_verification": verification,
        "current_step": "write_apa_draft",
        "error": None,
    }


def repair_draft_markdown(
    draft_markdown: str,
    *,
    paper_outline: list,
    specific_requirements: str = "",
    assessment_summary: str = "",
    sources: Optional[list] = None,
    available_documents: Optional[list] = None,
) -> tuple[str, WritingConstraints, dict]:
    """
    对已有草稿做一轮自动补写/压缩，并硬锁回大纲骨架。
    供 repair-agent-draft API 使用。
    """
    sections = _normalize_outline(paper_outline or [])
    sources = list(sources or [])
    constraints = extract_writing_constraints(
        specific=specific_requirements or "",
        assessment=assessment_summary or "",
    )
    matched_apply, unmatched_apply = bind_must_apply_documents(
        constraints.must_apply_documents, list(available_documents or [])
    )
    must_apply_block = format_must_apply_block(matched_apply)
    draft = rebuild_draft_to_outline(draft_markdown or "", sections)
    draft, _ = sanitize_citations(draft, sources)
    verification = verify_draft_against_constraints(
        draft, constraints, paper_outline=sections
    )
    if unmatched_apply:
        verification["must_apply_unmatched"] = unmatched_apply
    verification["must_apply_matched"] = [
        {"name": m.get("name"), "title": m.get("title"), "role": m.get("role")}
        for m in matched_apply
    ]
    cite_check = verify_citations(draft, sources)
    verification["citation_ok"] = cite_check.get("ok", True)
    verification["hallucinated_citations"] = cite_check.get("hallucinated") or []

    need_repair = bool(
        verification.get("missing_must_include")
        or (verification.get("structure") or {}).get("issues")
        or any(
            "word count" in (i or "").lower() for i in (verification.get("issues") or [])
        )
        or not verification.get("ok")
    )
    if need_repair:
        draft = _repair_draft_if_needed(
            draft,
            constraints=constraints,
            sources=sources,
            verification=verification,
            paper_outline=sections,
            must_apply_block=must_apply_block,
        )
        draft, _ = sanitize_citations(draft, sources)
        verification = verify_draft_against_constraints(
            draft, constraints, paper_outline=sections
        )
        cite_check = verify_citations(draft, sources)
        verification["citation_ok"] = cite_check.get("ok", True)
        verification["hallucinated_citations"] = cite_check.get("hallucinated") or []
        verification["repaired"] = True
    else:
        verification["repaired"] = False
    verification["repair_needed"] = False
    verification["repair_skipped"] = False
    return draft, constraints, verification
