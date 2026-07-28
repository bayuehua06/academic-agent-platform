"""写作约束：从 A/D 抽取通用 checklist，并做成稿轻量校验。

A（Assessment）与 D（Specific）同为硬约束源；页数不硬校验。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.services.llm_client import safe_invoke_chat
from app.services import summarizer as summarizer_module

logger = logging.getLogger(__name__)

_DEFAULT_WORD_TARGET = (2500, 3500)

_EXTRACT_SYSTEM = (
    "You extract HARD writing constraints for an academic paper draft. "
    "Assessment (A) and Specific requirements (D) are EQUALLY authoritative — "
    "A holds grading criteria and assignment musts; D holds execution details "
    "(length, style, must-apply documents).\n"
    "Return ONLY valid JSON with keys: "
    "checklist (string[]: each item a must-honor requirement from A and/or D), "
    "word_min (number|null), word_max (number|null), "
    "citation_style (string|null), language (string|null), "
    "must_include (string[]: topics/elements/rubric criteria that must appear), "
    "must_avoid (string[]), "
    "must_apply_documents (object[]: each {name: string, role_hint: string|null} — "
    "documents the draft MUST follow/apply when A/D say so, e.g. template, appendix, named file), "
    "other_notes (string). "
    "Do not invent constraints not present in the sources. "
    "Keep checklist items concrete and actionable. "
    "Prefer rubric/marking criteria and hard musts from Assessment into checklist/must_include. "
    "IMPORTANT for language: default to \"English\" for academic drafts unless the sources "
    "explicitly require Chinese or another language. "
    "Ignore page-count-only limits for word_min/word_max unless word counts are also given; "
    "you may mention pages in other_notes only."
)


@dataclass
class WritingConstraints:
    """结构化写作约束（字数只是其中一项）。"""

    checklist: List[str] = field(default_factory=list)
    word_min: Optional[int] = None
    word_max: Optional[int] = None
    citation_style: Optional[str] = None
    language: Optional[str] = None
    must_include: List[str] = field(default_factory=list)
    must_avoid: List[str] = field(default_factory=list)
    must_apply_documents: List[Dict[str, str]] = field(default_factory=list)
    other_notes: str = ""
    raw_specific: str = ""
    raw_assessment: str = ""
    # 兼容旧字段名
    raw_assessment_excerpt: str = ""
    source: str = "fallback"  # llm | fallback

    def word_target(self) -> Tuple[int, int]:
        if self.word_min is not None and self.word_max is not None:
            lo, hi = int(self.word_min), int(self.word_max)
            if lo > hi:
                lo, hi = hi, lo
            return max(500, lo), max(lo, hi)
        if self.word_min is not None:
            n = max(500, int(self.word_min))
            return n, int(n * 1.15)
        if self.word_max is not None:
            n = max(500, int(self.word_max))
            return int(n * 0.85), n
        return _DEFAULT_WORD_TARGET

    def to_prompt_block(self) -> str:
        """供每节写作 / 扩写 / 校验使用的硬约束块。"""
        lines: List[str] = [
            "=== HARD CONSTRAINTS (must honor; A Assessment + D Specific are co-equal) ==="
        ]
        lo, hi = self.word_target()
        lang = (self.language or "English").strip() or "English"
        lines.append(
            f"- Language: {lang} (HARD default = academic English for prose AND tables; "
            "translate Chinese outline/table drafts into English unless this line "
            "explicitly requires another language)."
        )
        lines.append(
            f"- Overall length target: {lo}-{hi} words (count in the output language). "
            "Do NOT exceed the max by padding; prefer cutting fluff over missing hard requirements."
        )
        lines.append(
            "- Page counts in sources are soft hints only; honor WORD targets above."
        )
        if self.citation_style:
            lines.append(f"- Citation style: {self.citation_style}")
        lines.append(
            "- CITATION INTEGRITY (non-negotiable): Cite ONLY from ALLOWED SOURCES. "
            "Out-of-library citations are forbidden. If ALLOWED SOURCES is NONE, use no in-text citations. "
            "Never invent authors, years, titles, DOIs, or findings."
        )
        if self.checklist:
            lines.append("- Checklist (from Assessment and/or Specific):")
            for item in self.checklist:
                lines.append(f"  * {item}")
        if self.must_include:
            lines.append("- Must include / address (rubric & requirements):")
            for item in self.must_include:
                lines.append(f"  * {item}")
        if self.must_avoid:
            lines.append("- Must avoid:")
            for item in self.must_avoid:
                lines.append(f"  * {item}")
        if self.must_apply_documents:
            lines.append("- Must apply / follow these documents (authoritative when content provided):")
            for item in self.must_apply_documents:
                name = item.get("name") or "?"
                hint = item.get("role_hint") or ""
                extra = f" [role_hint={hint}]" if hint else ""
                lines.append(f"  * {name}{extra}")
        if self.other_notes.strip():
            lines.append(f"- Other notes: {self.other_notes.strip()}")
        # A 硬块（优先保留评分相关段落）
        assess = (self.raw_assessment or self.raw_assessment_excerpt or "").strip()
        if assess:
            lines.append("- Assessment / grading HARD block (authoritative, verbatim excerpt):")
            lines.append(_prefer_rubric_excerpt(assess, limit=4500))
        if self.raw_specific.strip():
            lines.append("- Specific requirements HARD block (authoritative, verbatim):")
            lines.append(self.raw_specific.strip()[:4000])
        lines.append("=== END HARD CONSTRAINTS ===")
        return "\n".join(lines)

    def as_public_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        lo, hi = self.word_target()
        data["word_target"] = {"min": lo, "max": hi}
        return data


def _prefer_rubric_excerpt(text: str, limit: int = 4500) -> str:
    """过长时优先保留含评分/必须等关键词的段落。"""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    parts = re.split(r"\n{2,}", text)
    scored: List[Tuple[int, str]] = []
    keys = (
        "mark", "criterion", "criteria", "rubric", "must", "shall", "required",
        "不得", "必须", "评分", "分值", "及格", "fail", "pass", "weight", "assessment",
    )
    for p in parts:
        pl = p.lower()
        score = sum(1 for k in keys if k in pl)
        scored.append((score, p))
    scored.sort(key=lambda x: (-x[0], -len(x[1])))
    out: List[str] = []
    n = 0
    for _s, p in scored:
        if n >= limit:
            break
        take = p[: max(0, limit - n)]
        if take.strip():
            out.append(take)
            n += len(take) + 2
    if not out:
        return text[:limit]
    return "\n\n".join(out)[:limit]


def count_words(text: str) -> int:
    """粗算英文词数；中文按字近似。"""
    if not text:
        return 0
    en = re.findall(r"[A-Za-z0-9]+(?:'[A-Za-z]+)?(?:-[A-Za-z0-9]+)*", text)
    zh = re.findall(r"[\u4e00-\u9fff]", text)
    return len(en) + max(0, int(round(len(zh) / 1.5)))


def parse_word_target(*texts: str) -> Tuple[int, int]:
    """规则解析字数区间（抽取失败时的兜底）。不把纯页数当词数。"""
    blob = "\n".join(t for t in texts if t).lower()
    if not blob:
        return _DEFAULT_WORD_TARGET

    range_patterns = [
        r"(\d{3,5})\s*[-–—~to]{1,3}\s*(\d{3,5})\s*(?:english\s+)?(?:words?|word\s*count|词|字)",
        r"(\d{3,5})\s*[-–—~]\s*(\d{3,5})\s*(?:words?|词|字)",
        r"(?:between|约|大约)?\s*(\d{3,5})\s*(?:and|至|到)\s*(\d{3,5})\s*(?:english\s+)?(?:words?|词|字)",
    ]
    for pat in range_patterns:
        m = re.search(pat, blob, flags=re.I)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if lo > hi:
                lo, hi = hi, lo
            return max(500, lo), max(lo, hi)

    single_patterns = [
        r"(?:at\s+least|minimum|min\.?|不少于|至少|不低于)\s*(\d{3,5})\s*(?:english\s+)?(?:words?|词|字)",
        r"(?:approximately|about|around|约|大约)\s*(\d{3,5})\s*(?:english\s+)?(?:words?|词|字)",
        r"(?:word\s*count|字数|词数)\s*[:：]?\s*(\d{3,5})",
        r"(\d{3,5})\s*(?:english\s+)?(?:words?|word\s*count)\b",
    ]
    for pat in single_patterns:
        m = re.search(pat, blob, flags=re.I)
        if m:
            n = max(500, int(m.group(1)))
            return int(n * 0.9), int(n * 1.1)

    return _DEFAULT_WORD_TARGET


_MUST_APPLY_PATTERNS = [
    re.compile(
        r"(?:must\s+(?:follow|apply|use|adhere\s+to)|follow|apply|use|套用|遵循|按照|依据)\s+"
        r"(?:the\s+)?(?:document|template|appendix|file|指南|模板|附录|文档)\s*"
        r"[:：]?\s*[\"'「]?([^\"'\n。；;]{2,80})",
        re.I,
    ),
    re.compile(
        r"(?:必须|务必)(?:套用|遵循|按照|使用)\s*[「\"']?([^「\"'\n。；;]{2,80})",
        re.I,
    ),
]


def extract_must_apply_rule_based(*texts: str) -> List[Dict[str, str]]:
    """规则兜底：从 A/D 文本抓「必须套用文档」名称。"""
    blob = "\n".join(t for t in texts if t)
    found: List[Dict[str, str]] = []
    seen = set()
    for pat in _MUST_APPLY_PATTERNS:
        for m in pat.finditer(blob):
            name = (m.group(1) or "").strip(" .。,，;；:：\"'")
            if len(name) < 2:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            role_hint = ""
            low = name.lower()
            if any(k in low for k in ("background", "背景", "notebook")):
                role_hint = "BACKGROUND"
            elif any(k in low for k in ("outline", "大纲")):
                role_hint = "OUTLINE"
            elif any(k in low for k in ("assessment", "作业", "brief")):
                role_hint = "ASSESSMENT"
            found.append({"name": name, "role_hint": role_hint})
    return found[:10]


def bind_must_apply_documents(
    specs: List[Dict[str, str]],
    available_documents: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    将 must_apply 名称匹配到项目源文档。

    Returns:
        (matched_blocks, unmatched_names)
        matched_blocks: {name, title, role, content, matched: True}
    """
    matched: List[Dict[str, Any]] = []
    unmatched: List[str] = []
    docs = list(available_documents or [])

    for spec in specs or []:
        name = (spec.get("name") or "").strip()
        if not name:
            continue
        hint = (spec.get("role_hint") or "").strip().upper()
        name_l = name.lower()
        best = None
        best_score = 0
        for d in docs:
            title = (d.get("title") or "").strip()
            role = (d.get("role") or "").strip().upper()
            score = 0
            if hint and role == hint:
                score += 3
            tl = title.lower()
            if name_l and tl:
                if name_l == tl or name_l in tl or tl in name_l:
                    score += 5
                else:
                    # 词重叠
                    nt = set(re.findall(r"[a-z0-9]{3,}|[\u4e00-\u9fff]{2,}", name_l))
                    tt = set(re.findall(r"[a-z0-9]{3,}|[\u4e00-\u9fff]{2,}", tl))
                    score += min(3, len(nt & tt))
            if score > best_score:
                best_score = score
                best = d
        if best is None or best_score < 3:
            unmatched.append(name)
            continue
        content = (best.get("summary_text") or best.get("raw_text") or "").strip()
        matched.append(
            {
                "name": name,
                "title": best.get("title") or "",
                "role": best.get("role") or "",
                "content": content[:8000],
                "matched": True,
            }
        )
    return matched, unmatched


def format_must_apply_block(matched: List[Dict[str, Any]]) -> str:
    if not matched:
        return ""
    parts = [
        "=== MUST APPLY DOCUMENTS (authoritative; follow structure/rules in these) ==="
    ]
    for i, m in enumerate(matched, 1):
        parts.append(
            f"[{i}] {m.get('title') or m.get('name')} (role={m.get('role') or '?'})"
        )
        body = (m.get("content") or "").strip()
        parts.append(body[:6000] if body else "(document matched but empty content)")
    parts.append("=== END MUST APPLY DOCUMENTS ===")
    return "\n".join(parts)


def _fallback_constraints(specific: str, assessment: str) -> WritingConstraints:
    lo, hi = parse_word_target(specific, assessment)
    checklist: List[str] = []
    for line in re.split(r"[\n;；]+", specific or ""):
        item = line.strip(" -\t•*")
        if len(item) >= 8:
            checklist.append(item[:300])
    for line in re.split(r"[\n;；]+", assessment or ""):
        item = line.strip(" -\t•*")
        low = item.lower()
        if len(item) >= 12 and any(
            k in low
            for k in ("must", "mark", "criterion", "required", "必须", "评分", "不得")
        ):
            checklist.append(item[:300])
    checklist = checklist[:25]
    if not checklist and specific.strip():
        checklist = [specific.strip()[:500]]
    citation = None
    low = f"{specific}\n{assessment}".lower()
    if "apa" in low:
        citation = "APA 7th"
    language = "English"
    if any(k in low for k in ("中文", "汉语", "简体中文", "write in chinese", "in chinese")):
        language = "Chinese"
    elif "english" in low or "英文" in f"{specific}\n{assessment}":
        language = "English"
    must_apply = extract_must_apply_rule_based(specific, assessment)
    return WritingConstraints(
        checklist=checklist,
        word_min=lo,
        word_max=hi,
        citation_style=citation,
        language=language,
        must_include=[],
        must_avoid=[],
        must_apply_documents=must_apply,
        other_notes="",
        raw_specific=specific,
        raw_assessment=assessment,
        raw_assessment_excerpt=assessment[:2000],
        source="fallback",
    )


def _parse_json_object(text: str) -> Optional[dict]:
    raw = (text or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, flags=re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


def extract_writing_constraints(
    *,
    specific: str = "",
    assessment: str = "",
) -> WritingConstraints:
    """
    从 D + A 抽取通用硬约束（二者同等权威）。

    有 Key 时用默认（便宜）模型抽 JSON；失败则规则回退，并始终保留原文。
    """
    specific = (specific or "").strip()
    assessment = (assessment or "").strip()
    base = _fallback_constraints(specific, assessment)

    if not summarizer_module.has_openai_key() or (not specific and not assessment):
        return base

    user = (
        f"Specific requirements (D) — execution details:\n{specific[:5000] or '(none)'}\n\n"
        f"Assessment (A) — grading criteria & assignment contract (EQUALLY HARD):\n"
        f"{assessment[:5000] or '(none)'}\n"
    )
    raw = safe_invoke_chat(
        _EXTRACT_SYSTEM,
        user,
        temperature=0.1,
        max_input=12000,
        max_tokens=1600,
        purpose="default",
    )
    data = _parse_json_object(raw or "")
    if not data:
        logger.warning("约束抽取 JSON 失败，使用规则回退")
        return base

    def _str_list(key: str) -> List[str]:
        val = data.get(key) or []
        if isinstance(val, str):
            return [val.strip()] if val.strip() else []
        if not isinstance(val, list):
            return []
        return [str(x).strip() for x in val if str(x).strip()][:30]

    def _num(key: str) -> Optional[int]:
        val = data.get(key)
        if val is None or val == "":
            return None
        try:
            return int(val)
        except (TypeError, ValueError):
            return None

    def _must_apply_list() -> List[Dict[str, str]]:
        val = data.get("must_apply_documents") or []
        out: List[Dict[str, str]] = []
        if isinstance(val, str) and val.strip():
            return [{"name": val.strip(), "role_hint": ""}]
        if not isinstance(val, list):
            return extract_must_apply_rule_based(specific, assessment)
        for item in val[:10]:
            if isinstance(item, str) and item.strip():
                out.append({"name": item.strip(), "role_hint": ""})
            elif isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                out.append(
                    {
                        "name": name,
                        "role_hint": str(item.get("role_hint") or "").strip(),
                    }
                )
        return out or extract_must_apply_rule_based(specific, assessment)

    word_min = _num("word_min")
    word_max = _num("word_max")
    if word_min is None and word_max is None:
        word_min, word_max = base.word_min, base.word_max

    checklist = _str_list("checklist") or base.checklist
    lang_raw = data.get("language")
    language = str(lang_raw).strip() if lang_raw else (base.language or "English")
    if not language:
        language = "English"
    low_all = f"{specific}\n{assessment}\n{language}".lower()
    explicit_zh = any(
        k in low_all for k in ("中文", "汉语", "简体中文", "write in chinese", "in chinese")
    )
    if not explicit_zh and "chinese" in language.lower():
        language = "English"

    return WritingConstraints(
        checklist=checklist,
        word_min=word_min,
        word_max=word_max,
        citation_style=(
            str(data.get("citation_style")).strip()
            if data.get("citation_style")
            else base.citation_style
        ),
        language=language,
        must_include=_str_list("must_include"),
        must_avoid=_str_list("must_avoid"),
        must_apply_documents=_must_apply_list(),
        other_notes=str(data.get("other_notes") or "").strip(),
        raw_specific=specific,
        raw_assessment=assessment,
        raw_assessment_excerpt=assessment[:2000],
        source="llm",
    )


def verify_draft_against_constraints(
    draft: str,
    constraints: WritingConstraints,
    *,
    paper_outline: Optional[list] = None,
) -> Dict[str, Any]:
    """
    轻量成稿校验：字数 + must_include +（可选）大纲结构/表。

    不做昂贵全文 LLM 评审；返回 issues 列表供补写。
    """
    issues: List[str] = []
    words = count_words(draft)
    lo, hi = constraints.word_target()
    if words < int(lo * 0.85):
        issues.append(
            f"Word count too low: ~{words} words; target {lo}-{hi}."
        )
    # 收紧超标容差：超过 max 的 10%
    if words > int(hi * 1.10):
        issues.append(
            f"Word count too high: ~{words} words; target {lo}-{hi}. "
            "Compress without removing tables, headings, or hard requirements."
        )

    missing: List[str] = []
    draft_l = draft.lower()
    for item in constraints.must_include:
        tokens = [t for t in re.findall(r"[a-z0-9]{4,}|[\u4e00-\u9fff]{2,}", item.lower())]
        if not tokens:
            continue
        if not any(t in draft_l for t in tokens[:3]):
            missing.append(item)
    if missing:
        issues.append("Missing must-include topics: " + "; ".join(missing[:8]))

    structure: Dict[str, Any] = {"ok": True, "issues": [], "missing_tables": []}
    if paper_outline is not None:
        from app.services.structure_guard import verify_outline_structure

        structure = verify_outline_structure(draft, paper_outline)
        issues.extend(structure.get("issues") or [])

    return {
        "ok": not issues,
        "word_count": words,
        "word_target": {"min": lo, "max": hi},
        "issues": issues,
        "missing_must_include": missing,
        "structure": structure,
    }
