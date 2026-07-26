"""Node 3: APA Writer — 约束抽取 + 分节写作（Writer 模型）+ 轻量校验补写。"""

from __future__ import annotations

import logging
from typing import List, Optional

from app.agents.state import AcademicAgentState, LiteratureSource, OutlineSection
from app.services import summarizer as summarizer_module
from app.services.llm_client import resolve_model, safe_invoke_chat
from app.services.writing_constraints import (
    WritingConstraints,
    count_words,
    extract_writing_constraints,
    parse_word_target,
    verify_draft_against_constraints,
)

logger = logging.getLogger(__name__)

# re-export for tests that import from writer
allocate_section_words = None  # set below after def


_SECTION_SYSTEM = (
    "You are an academic writing assistant. Write ONE section of a scholarly paper "
    "in Markdown (APA 7th in-text citations only unless HARD CONSTRAINTS say otherwise).\n"
    "Hard rules:\n"
    "- DEFAULT LANGUAGE: academic English. Only write Chinese (or another language) "
    "if HARD CONSTRAINTS explicitly require it.\n"
    "- Output ONLY this section: the given heading line, then body paragraphs.\n"
    "- Do NOT write other sections, a title page, or a References list.\n"
    "- Cite ONLY from the provided source list.\n"
    "- Do NOT invent sources, findings, or DOIs.\n"
    "- Obey the HARD CONSTRAINTS block completely (length, style, must-include, must-avoid, language, etc.).\n"
    "- Hit the target word count for THIS section (±15%) with substantive analysis "
    "(define concepts, compare sources, address key_points)—not filler.\n"
    "- Stay consistent with the previous-section summary when provided."
)


def format_intext_citation(authors: List[str], year: str) -> str:
    """APA 7th 文内引用。"""
    year = year or "n.d."
    if not authors:
        return f"(Anonymous, {year})"

    def surname(name: str) -> str:
        name = name.strip()
        if "," in name:
            return name.split(",")[0].strip()
        parts = name.split()
        return parts[-1] if parts else name

    surnames = [surname(a) for a in authors]
    if len(surnames) == 1:
        return f"({surnames[0]}, {year})"
    if len(surnames) == 2:
        return f"({surnames[0]} & {surnames[1]}, {year})"
    return f"({surnames[0]} et al., {year})"


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


def _format_sources_for_prompt(sources: List[LiteratureSource], limit: int = 20) -> str:
    lines: list[str] = []
    for i, src in enumerate(sources[:limit]):
        authors = ", ".join(src.get("authors") or []) or "Anonymous"
        year = src.get("year") or "n.d."
        title = src.get("title") or "Untitled"
        doi = src.get("doi") or ""
        abstract = (src.get("abstract") or "").strip()[:600]
        cite = format_intext_citation(src.get("authors") or [], year)
        lines.append(
            f"[{i + 1}] {authors} ({year}). {title}. "
            f"Suggested in-text: {cite}"
            + (f" DOI: {doi}." if doi else ".")
            + (f"\nAbstract: {abstract}" if abstract else "")
        )
    return "\n\n".join(lines) if lines else "(no sources)"


def _ensure_heading(body: str, section: OutlineSection) -> str:
    text = (body or "").strip()
    heading = _heading_md(int(section.get("level") or 1), section.get("heading") or "Section")
    if not text:
        return heading + "\n\n"
    first = text.splitlines()[0].strip()
    if first.lstrip("#").strip().lower() == (section.get("heading") or "").lower():
        return text + "\n"
    return f"{heading}\n\n{text}\n"


def _section_max_tokens(word_target: int) -> int:
    return max(800, min(8000, int(word_target * 2.2) + 400))


def _prev_summary(text: str, limit: int = 500) -> str:
    body = (text or "").strip()
    if not body:
        return "(none — this is the first section)"
    return body[-limit:]


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
) -> Optional[str]:
    heading = section.get("heading") or f"Section {section_index + 1}"
    level = int(section.get("level") or 1)
    key_points = (section.get("key_points") or "").strip()
    lo, hi = constraints.word_target()
    user = (
        f"{constraints.to_prompt_block()}\n\n"
        f"This is section {section_index + 1} of {section_count}.\n"
        f"Overall paper length target: {lo}-{hi} English words.\n"
        f"TARGET FOR THIS SECTION ONLY: about {word_target} English words "
        f"(acceptable {int(word_target * 0.85)}-{int(word_target * 1.15)}).\n\n"
        f"Section heading (Markdown level {level}): {_heading_md(level, heading)}\n"
        f"key_points:\n{key_points or '(none)'}\n\n"
        f"Previous section ending (for continuity):\n{previous_summary}\n\n"
        f"Assessment summary (excerpt):\n{assessment[:2000] or '(none)'}\n\n"
        f"Background notes (excerpt):\n{backgrounds[:1800] or '(none)'}\n\n"
        f"Allowed sources:\n{_format_sources_for_prompt(sources)}\n"
    )
    return safe_invoke_chat(
        _SECTION_SYSTEM,
        user,
        temperature=0.45,
        max_input=16000,
        max_tokens=_section_max_tokens(word_target),
        purpose="writer",
    )


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
    expand = safe_invoke_chat(
        (
            "Expand the academic Markdown section below. Keep the same heading. "
            "Obey HARD CONSTRAINTS. DEFAULT language is English unless constraints "
            "explicitly require otherwise. Add substantive analysis and citations from the "
            "source list only. Do not invent sources. Output the full section."
        ),
        (
            f"{constraints.to_prompt_block()}\n\n"
            f"Current section (~{words} words) must grow by about {need} words "
            f"toward ~{word_target} words.\n\n"
            f"Sources:\n{_format_sources_for_prompt(sources)}\n\n"
            f"Section to expand:\n{body}\n"
        ),
        temperature=0.4,
        max_input=14000,
        max_tokens=_section_max_tokens(word_target),
        purpose="writer",
    )
    if expand and count_words(expand) > words:
        return _ensure_heading(expand, section)
    return body


def _repair_draft_if_needed(
    draft: str,
    *,
    constraints: WritingConstraints,
    sources: list,
    verification: dict,
) -> str:
    """对照 checklist / 字数做一轮补写。"""
    if verification.get("ok"):
        return draft
    issues = verification.get("issues") or []
    repaired = safe_invoke_chat(
        (
            "You revise an academic Markdown draft to satisfy unmet HARD CONSTRAINTS. "
            "Keep the same outline headings and APA in-text citations from the source list only. "
            "DEFAULT language is English unless HARD CONSTRAINTS explicitly require another language. "
            "Do not add a References list. Output the full revised Markdown draft."
        ),
        (
            f"{constraints.to_prompt_block()}\n\n"
            f"Unmet issues:\n- " + "\n- ".join(issues) + "\n\n"
            f"Sources:\n{_format_sources_for_prompt(sources)}\n\n"
            f"Current draft:\n{draft[:24000]}\n"
        ),
        temperature=0.35,
        max_input=28000,
        max_tokens=12000,
        purpose="writer",
    )
    if repaired and count_words(repaired) >= int(count_words(draft) * 0.8):
        logger.info("Writer 成稿补写完成")
        return repaired.strip() + "\n"
    logger.warning("Writer 成稿补写未采用（失败或过短）")
    return draft


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
    logger.info(
        "Writer model=%s constraints_source=%s 字数=%s-%s 分节=%s checklist=%s",
        resolve_model("writer"),
        constraints.source,
        target_min,
        target_max,
        budgets,
        len(constraints.checklist),
    )

    parts: List[str] = [
        "# Academic Draft\n",
        f"*Writer model: {resolve_model('writer')}; "
        f"target {target_min}-{target_max} words; "
        f"constraints={constraints.source}.*\n",
    ]
    ok_sections = 0
    prev = ""
    for i, section in enumerate(sections):
        raw = _write_section_llm(
            section=section,
            word_target=budgets[i],
            constraints=constraints,
            assessment=assessment,
            backgrounds=bg,
            sources=sources,
            section_index=i,
            section_count=len(sections),
            previous_summary=_prev_summary(prev),
        )
        if not raw:
            logger.warning("Writer 第 %s 节失败，用模板段落占位", i + 1)
            body = _section_paragraph(section, sources, i)
            parts.append(body)
            prev = body
            continue
        body = _ensure_heading(raw, section)
        body = _expand_section_if_short(
            body,
            section=section,
            word_target=budgets[i],
            constraints=constraints,
            sources=sources,
        )
        parts.append(body)
        prev = body
        ok_sections += 1

    if ok_sections == 0:
        return None, constraints, {"ok": False, "issues": ["all sections failed"]}

    draft = "\n".join(parts).strip() + "\n"
    verification = verify_draft_against_constraints(draft, constraints)
    if not verification.get("ok"):
        draft = _repair_draft_if_needed(
            draft,
            constraints=constraints,
            sources=sources,
            verification=verification,
        )
        verification = verify_draft_against_constraints(draft, constraints)

    logger.info(
        "Writer 完成：words≈%s target=%s-%s ok=%s issues=%s",
        verification.get("word_count"),
        target_min,
        target_max,
        verification.get("ok"),
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
        "# Academic Draft\n",
        f"*Keywords: {', '.join(keywords)}*\n",
        intro_extra,
    ]
    for i, section in enumerate(_normalize_outline(paper_outline)):
        parts.append(_section_paragraph(section, sources, i))
    return "\n".join(parts).strip() + "\n"


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
