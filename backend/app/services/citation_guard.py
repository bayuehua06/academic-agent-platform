"""文内引用护栏：禁止编造文献（系统硬规则 + 成稿清洗）。

最高优先级约束：模型只能引用用户/Zotero 提供的文献列表；
零文献时禁止任何 (Author, Year) / Author (Year) 形式的文内引用。
提示词写死 + 后处理剔除双保险。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 系统提示硬块（Writer / Polish / 扩写 / 补写必须嵌入，不可被作业要求覆盖）
# ---------------------------------------------------------------------------

CITATION_HARD_RULES = """\
=== CITATION INTEGRITY (NON-NEGOTIABLE; overrides any other instruction) ===
1. You may cite ONLY works listed under ALLOWED SOURCES below.
2. NEVER invent authors, years, titles, journals, DOIs, page numbers, findings, or quotes.
3. NEVER cite any work that is not on ALLOWED SOURCES — this is out-of-library and forbidden.
4. If ALLOWED SOURCES is empty / NONE, then every in-text citation would be out-of-library: \
use ZERO in-text citations. Do not use (Author, Year), Author (Year), "et al.", or a References list.
5. If a claim needs evidence you do not have, write analytically without naming a source \
that is not on ALLOWED SOURCES.
6. Do NOT add a References / Bibliography section; the system builds it from the real library.
7. Prefer the exact APA in-text forms listed next to each allowed source.
=== END CITATION INTEGRITY ==="""


YearKey = str  # "2020" | "n.d." | "2020a"
SurnameYear = Tuple[str, YearKey]


def surname_of(name: str) -> str:
    """作者名 → 姓氏（APA 文内用）。"""
    name = (name or "").strip()
    if not name:
        return ""
    if "," in name:
        return name.split(",")[0].strip()
    parts = name.split()
    return parts[-1] if parts else name


def _norm_year(year: Optional[str]) -> YearKey:
    y = (year or "").strip()
    if not y:
        return "n.d."
    m = re.search(r"(19|20)\d{2}[a-z]?", y, flags=re.I)
    if m:
        return m.group(0).lower()
    if y.lower() in {"n.d.", "nd", "n.d"}:
        return "n.d."
    return y.lower()


def _norm_surname(s: str) -> str:
    return re.sub(r"[^a-z]", "", (s or "").lower())


def build_allowed_surname_years(sources: Sequence[Dict[str, Any]] | Sequence[Any]) -> Set[SurnameYear]:
    """从文献列表构建允许的 (姓, 年) 集合（含 et al. 首作者）。"""
    allowed: Set[SurnameYear] = set()
    for src in sources or []:
        if not isinstance(src, dict):
            continue
        authors = src.get("authors") or []
        if isinstance(authors, str):
            authors = [authors]
        year = _norm_year(str(src.get("year") or ""))
        surnames = [_norm_surname(surname_of(str(a))) for a in authors]
        surnames = [s for s in surnames if s]
        if not surnames:
            allowed.add(("anonymous", year))
            continue
        # 任意署名作者 + 年都算合法（含 et al. 只写第一作者）
        for s in surnames:
            allowed.add((s, year))
        # n.d. 宽松：同年缺省也可对上无年条目
        if year == "n.d.":
            for s in surnames:
                allowed.add((s, "n.d."))
    return allowed


def format_intext_citation(authors: List[str], year: str) -> str:
    """APA 7th 括号文内引用。"""
    y = year or "n.d."
    if not authors:
        return f"(Anonymous, {y})"

    surnames = [surname_of(a) for a in authors if str(a).strip()]
    if not surnames:
        return f"(Anonymous, {y})"
    if len(surnames) == 1:
        return f"({surnames[0]}, {y})"
    if len(surnames) == 2:
        return f"({surnames[0]} & {surnames[1]}, {y})"
    return f"({surnames[0]} et al., {y})"


def format_allowed_sources_block(sources: Sequence[Dict[str, Any]] | Sequence[Any], limit: int = 40) -> str:
    """
    供提示词使用的允许文献块（含推荐文内引用形式）。
    列表为空时明确禁止一切引用。
    """
    rows: List[str] = []
    for i, src in enumerate(list(sources or [])[:limit]):
        if not isinstance(src, dict):
            continue
        authors = src.get("authors") or []
        if isinstance(authors, str):
            authors = [authors]
        authors = [str(a) for a in authors]
        year = str(src.get("year") or "n.d.")
        title = (src.get("title") or "Untitled").strip()
        doi = (src.get("doi") or "").strip()
        cite = format_intext_citation(authors, year)
        doi_bit = f" DOI:{doi}" if doi else ""
        rows.append(f"[{i + 1}] ALLOWED cite form {cite} — {title}{doi_bit}")

    if not rows:
        return (
            "ALLOWED SOURCES: NONE\n"
            "→ Any in-text citation would be out-of-library and is forbidden. "
            "Write with zero (Author, Year) / Author (Year) citations."
        )
    return "ALLOWED SOURCES (cite ONLY these; out-of-library citations are forbidden):\n" + "\n".join(rows)


# 括号内单条：Smith, 2020 / Smith & Jones, 2020 / Smith et al., 2020
_PAREN_SEGMENT = re.compile(
    r"^\s*(?P<authors>.+?),\s*(?P<year>(?:19|20)\d{2}[a-z]?|n\.d\.)\b",
    re.I,
)
# 叙述式：Smith (2020) / Smith and Jones (2020) / Smith et al. (2020)
_NARRATIVE = re.compile(
    r"(?P<authors>\b[A-Z][A-Za-z\-']+"
    r"(?:\s+(?:and|&)\s+[A-Z][A-Za-z\-']+)?"
    r"(?:\s+et\s+al\.)?)"
    r"\s*\((?P<year>(?:19|20)\d{2}[a-z]?|n\.d\.)\)",
)


def _first_author_key(authors_blob: str) -> str:
    """从 'Smith & Jones' / 'Smith et al.' / 'Smith and Jones' 取第一作者姓。"""
    blob = (authors_blob or "").strip()
    blob = re.sub(r"\s+et\s+al\.?\s*$", "", blob, flags=re.I).strip()
    # 取 & / and 前的第一段
    parts = re.split(r"\s+(?:&|and)\s+", blob, maxsplit=1, flags=re.I)
    first = parts[0].strip()
    # 可能是 "Smith, J." — 取逗号前
    if "," in first:
        first = first.split(",")[0].strip()
    # 多词取最后一个词作姓（John Smith → Smith）；单字即姓
    toks = first.split()
    if len(toks) >= 2 and toks[0][0:1].isupper() and len(toks[0]) <= 3:
        # 像 "J Smith" 少见；默认取末词
        return _norm_surname(toks[-1])
    return _norm_surname(toks[-1] if toks else first)


def _is_allowed(authors_blob: str, year: str, allowed: Set[SurnameYear]) -> bool:
    key = (_first_author_key(authors_blob), _norm_year(year))
    if key in allowed:
        return True
    # 年宽松：库里是 n.d. 时也接受同姓 + 数字年？不接受，避免放行幻觉年
    # 反：文内 n.d. 对上有年的库条目 — 偏严，不自动放行
    return False


def iter_suspicious_citations(
    text: str,
    allowed: Set[SurnameYear],
) -> List[Dict[str, Any]]:
    """找出文中疑似不在允许列表的文内引用。"""
    found: List[Dict[str, Any]] = []
    if not text:
        return found

    # 1) 括号簇：(A, 2020; B, 2021, p. 3)
    for m in re.finditer(r"\(([^)]{3,200})\)", text):
        inner = m.group(1)
        # 跳过非引用括号（过短、无年）
        if not re.search(r"(?:19|20)\d{2}|n\.d\.", inner, flags=re.I):
            continue
        # 纯页码 (p. 12) 跳过
        if re.fullmatch(r"\s*pp?\.\s*\d+[-–]?\d*\s*", inner, flags=re.I):
            continue
        segments = re.split(r"\s*;\s*", inner)
        bad_bits: List[str] = []
        for seg in segments:
            sm = _PAREN_SEGMENT.match(seg.strip())
            if not sm:
                # 可能是 "see Smith, 2020, p. 3" — 再试去前缀
                sm2 = _PAREN_SEGMENT.search(seg.strip())
                if not sm2:
                    continue
                sm = sm2
            authors = sm.group("authors")
            year = sm.group("year")
            # 排除不像人名的（URL、eqn 等）
            if len(_first_author_key(authors)) < 2:
                continue
            if not _is_allowed(authors, year, allowed):
                bad_bits.append(f"{authors.strip()}, {year}")
        if bad_bits:
            found.append(
                {
                    "kind": "parenthetical",
                    "span": m.group(0),
                    "start": m.start(),
                    "end": m.end(),
                    "bad": bad_bits,
                }
            )

    # 2) 叙述式
    for m in _NARRATIVE.finditer(text):
        authors = m.group("authors")
        year = m.group("year")
        if _is_allowed(authors, year, allowed):
            continue
        found.append(
            {
                "kind": "narrative",
                "span": m.group(0),
                "start": m.start(),
                "end": m.end(),
                "bad": [f"{authors}, {year}"],
            }
        )
    return found


def sanitize_citations(
    text: str,
    sources: Sequence[Dict[str, Any]] | Sequence[Any],
) -> Tuple[str, List[str]]:
    """
    剔除不在允许列表中的文内引用标记。

    括号内多引用（用 ; 分隔）时只去掉非法段，保留合法段。

    Returns:
        (cleaned_text, removed_labels)
    """
    allowed = build_allowed_surname_years(sources)
    if not text:
        return text, []

    removed: List[str] = []
    cleaned = text

    # --- 括号簇：按段过滤 ---
    def _rewrite_paren(match: re.Match[str]) -> str:
        inner = match.group(1)
        if not re.search(r"(?:19|20)\d{2}|n\.d\.", inner, flags=re.I):
            return match.group(0)
        if re.fullmatch(r"\s*pp?\.\s*\d+[-–]?\d*\s*", inner, flags=re.I):
            return match.group(0)
        segments = re.split(r"\s*;\s*", inner)
        kept: List[str] = []
        for seg in segments:
            raw_seg = seg.strip()
            sm = _PAREN_SEGMENT.match(raw_seg) or _PAREN_SEGMENT.search(raw_seg)
            if not sm:
                # 不像引用的片段原样保留（少见）
                kept.append(raw_seg)
                continue
            authors = sm.group("authors")
            year = sm.group("year")
            if len(_first_author_key(authors)) < 2:
                kept.append(raw_seg)
                continue
            if _is_allowed(authors, year, allowed):
                kept.append(raw_seg)
            else:
                removed.append(f"{authors.strip()}, {year}")
        if not kept:
            return ""
        if len(kept) == len(segments) and all(
            k == s.strip() for k, s in zip(kept, segments)
        ):
            return match.group(0)
        return "(" + "; ".join(kept) + ")"

    cleaned = re.sub(r"\(([^)]{3,200})\)", _rewrite_paren, cleaned)

    # --- 叙述式：整段删除非法 ---
    def _rewrite_narrative(match: re.Match[str]) -> str:
        authors = match.group("authors")
        year = match.group("year")
        if _is_allowed(authors, year, allowed):
            return match.group(0)
        removed.append(f"{authors}, {year}")
        return ""

    cleaned = _NARRATIVE.sub(_rewrite_narrative, cleaned)

    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r" +([,.;:])", r"\1", cleaned)
    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    if removed:
        logger.warning("已剔除疑似编造文内引用 %s 处: %s", len(removed), removed[:12])
    return cleaned, removed


def verify_citations(
    text: str,
    sources: Sequence[Dict[str, Any]] | Sequence[Any],
) -> Dict[str, Any]:
    """成稿校验：返回 hallucinated 列表与是否通过。"""
    allowed = build_allowed_surname_years(sources)
    suspects = iter_suspicious_citations(text, allowed)
    labels: List[str] = []
    for s in suspects:
        labels.extend(s.get("bad") or [])
    # 去重保序
    seen: Set[str] = set()
    uniq: List[str] = []
    for lab in labels:
        if lab not in seen:
            seen.add(lab)
            uniq.append(lab)
    return {
        "ok": len(uniq) == 0,
        "hallucinated": uniq,
        "allowed_count": len(allowed),
        "source_count": len(list(sources or [])),
    }
