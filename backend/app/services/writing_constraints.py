"""写作约束：从 A/D 抽取通用 checklist，并做成稿轻量校验。"""

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
    "Return ONLY valid JSON with keys: "
    "checklist (string[]: each item a must-honor requirement), "
    "word_min (number|null), word_max (number|null), "
    "citation_style (string|null), language (string|null), "
    "must_include (string[]: topics/elements that must appear), "
    "must_avoid (string[]), "
    "other_notes (string). "
    "Do not invent constraints not present in the sources. "
    "Keep checklist items concrete and actionable. "
    "IMPORTANT for language: default to \"English\" for academic drafts unless the sources "
    "explicitly require Chinese or another language."
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
    other_notes: str = ""
    raw_specific: str = ""
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
        lines: List[str] = ["=== HARD CONSTRAINTS (must honor across the whole paper) ==="]
        lo, hi = self.word_target()
        lang = (self.language or "English").strip() or "English"
        lines.append(f"- Language: {lang} (DEFAULT is English unless explicitly overridden).")
        lines.append(f"- Overall length target: {lo}-{hi} words (count in the output language).")
        if self.citation_style:
            lines.append(f"- Citation style: {self.citation_style}")
        if self.checklist:
            lines.append("- Checklist:")
            for item in self.checklist:
                lines.append(f"  * {item}")
        if self.must_include:
            lines.append("- Must include / address:")
            for item in self.must_include:
                lines.append(f"  * {item}")
        if self.must_avoid:
            lines.append("- Must avoid:")
            for item in self.must_avoid:
                lines.append(f"  * {item}")
        if self.other_notes.strip():
            lines.append(f"- Other notes: {self.other_notes.strip()}")
        # 始终附上原文，避免抽取遗漏
        if self.raw_specific.strip():
            lines.append("- Original specific requirements (verbatim):")
            lines.append(self.raw_specific.strip()[:4000])
        if self.raw_assessment_excerpt.strip():
            lines.append("- Assessment excerpt:")
            lines.append(self.raw_assessment_excerpt.strip()[:2000])
        lines.append("=== END HARD CONSTRAINTS ===")
        return "\n".join(lines)

    def as_public_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        lo, hi = self.word_target()
        data["word_target"] = {"min": lo, "max": hi}
        return data


def count_words(text: str) -> int:
    """粗算英文词数；中文按字近似。"""
    if not text:
        return 0
    en = re.findall(r"[A-Za-z0-9]+(?:'[A-Za-z]+)?(?:-[A-Za-z0-9]+)*", text)
    zh = re.findall(r"[\u4e00-\u9fff]", text)
    return len(en) + max(0, int(round(len(zh) / 1.5)))


def parse_word_target(*texts: str) -> Tuple[int, int]:
    """规则解析字数区间（抽取失败时的兜底）。"""
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


def _fallback_constraints(specific: str, assessment: str) -> WritingConstraints:
    lo, hi = parse_word_target(specific, assessment)
    checklist: List[str] = []
    for line in re.split(r"[\n;；]+", specific or ""):
        item = line.strip(" -\t•*")
        if len(item) >= 8:
            checklist.append(item[:300])
    checklist = checklist[:20]
    if not checklist and specific.strip():
        checklist = [specific.strip()[:500]]
    citation = None
    low = f"{specific}\n{assessment}".lower()
    if "apa" in low:
        citation = "APA 7th"
    # 学术草稿默认英文；仅当明确要求中文时才改
    language = "English"
    if any(k in low for k in ("中文", "汉语", "简体中文", "write in chinese", "in chinese")):
        language = "Chinese"
    elif "english" in low or "英文" in f"{specific}\n{assessment}":
        language = "English"
    return WritingConstraints(
        checklist=checklist,
        word_min=lo,
        word_max=hi,
        citation_style=citation,
        language=language,
        must_include=[],
        must_avoid=[],
        other_notes="",
        raw_specific=specific,
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
    从 D + A 抽取通用硬约束。

    有 Key 时用默认（便宜）模型抽 JSON；失败则规则回退，并始终保留原文。
    """
    specific = (specific or "").strip()
    assessment = (assessment or "").strip()
    base = _fallback_constraints(specific, assessment)

    if not summarizer_module.has_openai_key() or (not specific and not assessment):
        return base

    user = (
        f"Specific requirements (D):\n{specific[:5000] or '(none)'}\n\n"
        f"Assessment summary (A excerpt):\n{assessment[:3500] or '(none)'}\n"
    )
    raw = safe_invoke_chat(
        _EXTRACT_SYSTEM,
        user,
        temperature=0.1,
        max_input=10000,
        max_tokens=1200,
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

    word_min = _num("word_min")
    word_max = _num("word_max")
    if word_min is None and word_max is None:
        word_min, word_max = base.word_min, base.word_max

    checklist = _str_list("checklist") or base.checklist
    lang_raw = data.get("language")
    language = str(lang_raw).strip() if lang_raw else (base.language or "English")
    if not language:
        language = "English"
    # 防止模型因中文摘要误判成中文稿
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
        citation_style=(str(data.get("citation_style")).strip() if data.get("citation_style") else base.citation_style),
        language=language,
        must_include=_str_list("must_include"),
        must_avoid=_str_list("must_avoid"),
        other_notes=str(data.get("other_notes") or "").strip(),
        raw_specific=specific,
        raw_assessment_excerpt=assessment[:2000],
        source="llm",
    )


def verify_draft_against_constraints(
    draft: str,
    constraints: WritingConstraints,
) -> Dict[str, Any]:
    """
    轻量成稿校验：字数 + must_include 关键词命中。

    不做昂贵全文 LLM 评审；返回 issues 列表供补写。
    """
    issues: List[str] = []
    words = count_words(draft)
    lo, hi = constraints.word_target()
    # 允许略低于下限 15%
    if words < int(lo * 0.85):
        issues.append(
            f"Word count too low: ~{words} words; target {lo}-{hi}."
        )
    if words > int(hi * 1.25):
        issues.append(
            f"Word count too high: ~{words} words; target {lo}-{hi}."
        )

    missing: List[str] = []
    draft_l = draft.lower()
    for item in constraints.must_include:
        # 用条目中较长的词做粗匹配
        tokens = [t for t in re.findall(r"[a-z0-9]{4,}|[\u4e00-\u9fff]{2,}", item.lower())]
        if not tokens:
            continue
        if not any(t in draft_l for t in tokens[:3]):
            missing.append(item)
    if missing:
        issues.append("Missing must-include topics: " + "; ".join(missing[:8]))

    return {
        "ok": not issues,
        "word_count": words,
        "word_target": {"min": lo, "max": hi},
        "issues": issues,
        "missing_must_include": missing,
    }
