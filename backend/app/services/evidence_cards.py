"""Writer/Polish 证据卡：本地 abstract、URL 全文、DOI enrich、PDF 与 section 级 chunk 选择。"""

from __future__ import annotations

import asyncio
import html
import logging
import re
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import quote

import httpx
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import Literature
from app.services.citation_guard import format_intext_citation

logger = logging.getLogger(__name__)
settings = get_settings()

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "into",
    "about",
    "using",
    "study",
    "section",
    "paper",
    "analysis",
    "discussion",
    "introduction",
    "conclusion",
    "literature",
}


def _clean_text(text: Optional[str]) -> str:
    raw = html.unescape(text or "")
    raw = re.sub(r"<script\b.*?</script>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<style\b.*?</style>", " ", raw, flags=re.I | re.S)
    raw = _TAG_RE.sub(" ", raw)
    raw = raw.replace("\x00", " ")
    raw = _SPACE_RE.sub(" ", raw).strip()
    return raw


def extract_pdf_text(
    data: bytes,
    *,
    max_pages: Optional[int] = None,
    max_chars: Optional[int] = None,
) -> str:
    """从 PDF 字节抽取纯文本（限页/限长）。"""
    if not data:
        return ""
    try:
        from pypdf import PdfReader
    except ImportError:
        logger.warning("pypdf 未安装，跳过 PDF 证据抽取")
        return ""
    page_limit = max_pages if max_pages is not None else settings.writer_evidence_pdf_max_pages
    char_limit = max_chars if max_chars is not None else settings.writer_evidence_pdf_max_chars
    try:
        reader = PdfReader(BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        logger.warning("PDF 解析失败: %s", exc)
        return ""
    parts: List[str] = []
    for i, page in enumerate(reader.pages):
        if i >= max(1, page_limit):
            break
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            text = ""
        text = _clean_text(text)
        if text:
            parts.append(text)
        joined = "\n\n".join(parts)
        if len(joined) >= char_limit:
            return joined[:char_limit]
    return "\n\n".join(parts)[:char_limit]


def _split_chunks(text: str, max_chars: int = 900, overlap: int = 120) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    paras = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    if not paras:
        paras = [text]
    chunks: List[str] = []
    buf = ""
    for para in paras:
        if len(para) > max_chars * 2:
            start = 0
            while start < len(para):
                end = min(len(para), start + max_chars)
                piece = para[start:end].strip()
                if piece:
                    chunks.append(piece)
                start = max(start + max_chars - overlap, end)
            continue
        if not buf:
            buf = para
        elif len(buf) + 2 + len(para) <= max_chars:
            buf += "\n\n" + para
        else:
            chunks.append(buf)
            buf = para
    if buf:
        chunks.append(buf)
    return chunks


def _extract_keywords(heading: str, key_points: str) -> List[str]:
    text = f"{heading}\n{key_points or ''}"
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9\-_/]{2,}", text)
    seen: List[str] = []
    for tok in tokens:
        low = tok.lower()
        if low in _STOPWORDS:
            continue
        if low not in seen:
            seen.append(low)
    return seen[: max(1, settings.writer_evidence_keyword_top_n)]


def _score_chunk(chunk: str, keywords: Sequence[str]) -> int:
    low = (chunk or "").lower()
    hits = 0
    for kw in keywords:
        if kw and kw in low:
            hits += 1
    return hits


def select_evidence_excerpt(
    src: Dict[str, Any],
    *,
    heading: str,
    key_points: str,
) -> Dict[str, Any]:
    """为当前 section 从 source 里选证据片段；失败时走 abstract / metadata 回退。"""
    keywords = _extract_keywords(heading, key_points)
    fulltext = (src.get("evidence_text") or "").strip()
    abstract = (src.get("abstract") or "").strip()
    chunks = _split_chunks(fulltext)[: max(1, settings.writer_evidence_max_chunks_per_source * 8)]
    scored: List[tuple[int, str]] = []
    for chunk in chunks:
        score = _score_chunk(chunk, keywords)
        if score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda x: (-x[0], len(x[1])))
    topk = [c for _s, c in scored[: settings.writer_evidence_top_k]]
    best = scored[0][0] if scored else 0
    no_candidates = not topk
    below_min = best < settings.writer_evidence_best_score_min
    should_fallback = False
    mode = (settings.writer_evidence_fallback_mode or "both").strip().lower()
    if mode == "empty_only":
        should_fallback = no_candidates
    elif mode == "threshold_only":
        should_fallback = below_min
    else:
        should_fallback = no_candidates or below_min

    if topk and not should_fallback:
        excerpt = "\n\n".join(topk[: settings.writer_evidence_max_chunks_per_source])
        excerpt = excerpt[: settings.writer_evidence_max_chars_per_section]
        return {
            "tier": src.get("evidence_tier") or "full_resource",
            "evidence_source": src.get("evidence_source") or "url",
            "excerpt": excerpt,
            "score": best,
            "keywords": keywords,
            "fallback": False,
        }

    if abstract:
        return {
            "tier": "abstract",
            "evidence_source": src.get("evidence_source") or "zotero",
            "excerpt": abstract[: min(2000, settings.writer_evidence_max_chars_per_section)],
            "score": best,
            "keywords": keywords,
            "fallback": True,
        }

    return {
        "tier": "metadata_only",
        "evidence_source": src.get("evidence_source") or "none",
        "excerpt": "",
        "score": best,
        "keywords": keywords,
        "fallback": True,
    }


def format_allowed_sources_with_evidence(
    sources: Sequence[Dict[str, Any]] | Sequence[Any],
    *,
    heading: str,
    key_points: str,
    limit: int = 40,
) -> str:
    """Writer/Polish 用：署名 + tier + 当前 section 的证据摘录。"""
    rows: List[str] = []
    for i, raw in enumerate(list(sources or [])[:limit]):
        if not isinstance(raw, dict):
            continue
        authors = raw.get("authors") or []
        if isinstance(authors, str):
            authors = [authors]
        authors = [str(a) for a in authors]
        year = str(raw.get("year") or "n.d.")
        title = (raw.get("title") or "Untitled").strip()
        doi = (raw.get("doi") or "").strip()
        cite = format_intext_citation(authors, year)
        picked = select_evidence_excerpt(raw, heading=heading, key_points=key_points)
        doi_bit = f" DOI:{doi}" if doi else ""
        rows.append(
            f"[{i + 1}] ALLOWED cite form {cite} — {title}{doi_bit} "
            f"| tier={picked['tier']} | source={picked['evidence_source']}"
        )
        if picked["excerpt"]:
            rows.append(
                "    Evidence excerpt for this section: "
                + picked["excerpt"].replace("\n", " ")
            )
        else:
            rows.append(
                "    Evidence excerpt: NONE — metadata only; do not invent findings, "
                "methods, numbers, or conclusions from this source."
            )
    if not rows:
        return (
            "ALLOWED SOURCES: NONE\n"
            "→ Any in-text citation would be out-of-library and is forbidden. "
            "Write with zero citations."
        )
    return "ALLOWED SOURCES WITH EVIDENCE (cite ONLY these; ground claims in the evidence excerpts):\n" + "\n".join(rows)


def _parse_crossref_abstract(text: str) -> str:
    cleaned = re.sub(r"</?jats:[^>]+>", " ", text or "", flags=re.I)
    return _clean_text(cleaned)


def _parse_openalex_abstract(inv: Dict[str, Any]) -> str:
    if not isinstance(inv, dict):
        return ""
    pairs: List[tuple[int, str]] = []
    for word, positions in inv.items():
        if not isinstance(positions, list):
            continue
        for pos in positions:
            if isinstance(pos, int):
                pairs.append((pos, str(word)))
    pairs.sort(key=lambda x: x[0])
    return " ".join(word for _pos, word in pairs).strip()


async def _fetch_openalex_abstract(doi: str, client: httpx.AsyncClient) -> str:
    if not doi:
        return ""
    url = f"https://api.openalex.org/works/https://doi.org/{quote(doi, safe='')}"
    r = await client.get(url)
    if r.status_code != 200:
        return ""
    data = r.json()
    return _parse_openalex_abstract(data.get("abstract_inverted_index") or {})


async def _fetch_crossref_abstract(doi: str, client: httpx.AsyncClient) -> str:
    if not doi:
        return ""
    url = f"https://api.crossref.org/works/{quote(doi, safe='')}"
    r = await client.get(url)
    if r.status_code != 200:
        return ""
    data = r.json()
    msg = data.get("message") or {}
    return _parse_crossref_abstract(msg.get("abstract") or "")


async def _fetch_url_text(url: str, client: httpx.AsyncClient) -> str:
    if not url:
        return ""
    r = await client.get(url, follow_redirects=True)
    ctype = (r.headers.get("content-type") or "").lower()
    if r.status_code != 200:
        return ""
    if "pdf" in ctype or url.lower().endswith(".pdf"):
        return extract_pdf_text(r.content)
    if "html" not in ctype and "text/" not in ctype:
        return ""
    text = r.text
    body_match = re.search(r"<body\b[^>]*>(.*?)</body>", text, flags=re.I | re.S)
    if body_match:
        text = body_match.group(1)
    cleaned = _clean_text(text)
    return cleaned[: settings.writer_evidence_pdf_max_chars]


def _fetch_zotero_pdf_text_sync(zot_svc: Any, item_key: str) -> str:
    """同步：拉 Zotero PDF 附件并抽文本。"""
    keys = zot_svc.list_pdf_attachment_keys(item_key)
    for att_key in keys[:2]:
        blob = zot_svc.download_file_bytes(att_key)
        text = extract_pdf_text(blob)
        if text.strip():
            return text
    return ""


async def _fetch_zotero_pdf_text(zot_svc: Any, item_key: str) -> str:
    if not zot_svc or not item_key:
        return ""
    try:
        return await asyncio.to_thread(_fetch_zotero_pdf_text_sync, zot_svc, item_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Zotero PDF 证据失败 item=%s: %s", item_key, exc)
        return ""


async def _resolve_unpaywall_pdf_url(doi: str, client: httpx.AsyncClient) -> str:
    email = (settings.writer_evidence_unpaywall_email or "").strip()
    if not doi or not email:
        return ""
    url = f"https://api.unpaywall.org/v2/{quote(doi, safe='')}?email={quote(email)}"
    r = await client.get(url)
    if r.status_code != 200:
        return ""
    data = r.json() if r.content else {}
    best = data.get("best_oa_location") or {}
    pdf_url = (best.get("url_for_pdf") or "").strip()
    if pdf_url:
        return pdf_url
    for loc in data.get("oa_locations") or []:
        if not isinstance(loc, dict):
            continue
        candidate = (loc.get("url_for_pdf") or "").strip()
        if candidate:
            return candidate
    return (best.get("url") or "").strip()


async def _fetch_unpaywall_pdf_text(doi: str, client: httpx.AsyncClient) -> str:
    pdf_url = await _resolve_unpaywall_pdf_url(doi, client)
    if not pdf_url:
        return ""
    try:
        r = await client.get(pdf_url, follow_redirects=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unpaywall PDF 下载失败 doi=%s: %s", doi, exc)
        return ""
    if r.status_code != 200:
        return ""
    ctype = (r.headers.get("content-type") or "").lower()
    if "pdf" in ctype or pdf_url.lower().endswith(".pdf"):
        return extract_pdf_text(r.content)
    if "html" in ctype:
        text = r.text
        body_match = re.search(r"<body\b[^>]*>(.*?)</body>", text, flags=re.I | re.S)
        if body_match:
            text = body_match.group(1)
        return _clean_text(text)[: settings.writer_evidence_pdf_max_chars]
    return extract_pdf_text(r.content)


def evidence_content_key_for_source(src: Dict[str, Any]) -> str:
    """用于判断全文缓存是否仍对应当前文献标识（zotero/url/doi）。"""
    zkey = (src.get("zotero_item_key") or "").strip()
    url = (src.get("landing_url") or src.get("url") or "").strip()
    doi = (src.get("doi") or "").strip().lower()
    return f"z:{zkey}|u:{url}|d:{doi}"


def _truncate_evidence_text(text: str) -> str:
    limit = max(1000, int(settings.writer_evidence_pdf_max_chars))
    return (text or "")[:limit]


def _cached_fulltext_usable(src: Dict[str, Any]) -> bool:
    """有全文缓存且 content key 匹配（或旧数据无 key）时可跳过网络。"""
    if settings.writer_evidence_force_refresh:
        return False
    text = (src.get("evidence_text") or "").strip()
    if not text:
        return False
    stored_key = (src.get("evidence_content_key") or "").strip()
    current_key = evidence_content_key_for_source(src)
    if stored_key and stored_key != current_key:
        return False
    return True


async def build_evidence_cards(
    sources: Sequence[Dict[str, Any]],
    *,
    project: Any = None,
) -> List[Dict[str, Any]]:
    """
    补齐 evidence_text / tier / source。

    优先级：DB/入参全文缓存 → landing URL → Zotero PDF → Unpaywall OA PDF
    → local/enrich abstract → metadata_only

    缓存的是全文；按章 excerpt 仍由 select_evidence_excerpt 现算。
    """
    out: List[Dict[str, Any]] = []
    timeout = httpx.Timeout(settings.writer_evidence_http_timeout_seconds)
    zot_svc = None
    if project is not None and settings.writer_evidence_enable_zotero_pdf:
        try:
            from app.services.zotero_service import zotero_for_project

            zot_svc = zotero_for_project(project)
            if not getattr(zot_svc, "is_configured", False):
                zot_svc = None
        except Exception as exc:  # noqa: BLE001
            logger.warning("证据卡 Zotero 客户端不可用: %s", exc)
            zot_svc = None

    async with httpx.AsyncClient(
        timeout=timeout, headers={"User-Agent": settings.writer_evidence_user_agent}
    ) as client:
        enrich_left = max(0, settings.writer_evidence_enrich_max_sources)
        pdf_left = max(0, settings.writer_evidence_pdf_max_sources)
        cache_hits = 0
        for raw in sources or []:
            if not isinstance(raw, dict):
                continue
            src = dict(raw)
            abstract = (src.get("abstract") or "").strip()
            url = (src.get("landing_url") or src.get("url") or "").strip()
            doi = (src.get("doi") or "").strip()
            zkey = (src.get("zotero_item_key") or "").strip()
            content_key = evidence_content_key_for_source(src)
            evidence_text = ""
            evidence_source = "none"
            tier = "metadata_only"

            # 0) 复用已缓存全文（跨章/跨次 run）；excerpt 仍按章现算
            if _cached_fulltext_usable(src):
                evidence_text = _truncate_evidence_text(src.get("evidence_text") or "")
                tier = "full_resource"
                evidence_source = (src.get("evidence_source") or "cache").strip() or "cache"
                cache_hits += 1
            else:
                # 1) landing / URL 全文（含 PDF URL）
                if url:
                    try:
                        evidence_text = await _fetch_url_text(url, client)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("抓取 URL 证据失败 %s: %s", url, exc)
                        evidence_text = ""
                    if evidence_text:
                        tier = "full_resource"
                        evidence_source = "landing"

                # 2) Zotero PDF 附件
                if (
                    not evidence_text
                    and zot_svc
                    and zkey
                    and pdf_left > 0
                    and settings.writer_evidence_enable_zotero_pdf
                ):
                    pdf_left -= 1
                    evidence_text = await _fetch_zotero_pdf_text(zot_svc, zkey)
                    if evidence_text:
                        tier = "full_resource"
                        evidence_source = "zotero_pdf"

                # 3) Unpaywall OA PDF
                if (
                    not evidence_text
                    and doi
                    and pdf_left > 0
                    and settings.writer_evidence_enable_unpaywall
                    and (settings.writer_evidence_unpaywall_email or "").strip()
                ):
                    pdf_left -= 1
                    try:
                        evidence_text = await _fetch_unpaywall_pdf_text(doi, client)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Unpaywall 证据失败 doi=%s: %s", doi, exc)
                        evidence_text = ""
                    if evidence_text:
                        tier = "full_resource"
                        evidence_source = "unpaywall"

                # 4) 本地 abstract
                if abstract and not evidence_text:
                    tier = "abstract"
                    evidence_source = src.get("evidence_source") or "zotero"

                # 5) DOI abstract enrich
                if not abstract and not evidence_text and doi and enrich_left > 0:
                    enrich_left -= 1
                    for fetcher, label in (
                        (_fetch_openalex_abstract, "openalex"),
                        (_fetch_crossref_abstract, "crossref"),
                    ):
                        try:
                            abstract = (await fetcher(doi, client)).strip()
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("DOI enrich 失败 %s %s: %s", label, doi, exc)
                            abstract = ""
                        if abstract:
                            evidence_source = label
                            tier = "abstract"
                            break

                if not evidence_text and not abstract:
                    tier = "metadata_only"
                    evidence_source = evidence_source or "none"

            if evidence_text:
                evidence_text = _truncate_evidence_text(evidence_text)

            src["abstract"] = abstract
            src["landing_url"] = url or None
            src["evidence_text"] = evidence_text
            src["evidence_tier"] = tier
            src["evidence_source"] = evidence_source
            src["evidence_content_key"] = content_key if evidence_text else None
            out.append(src)
        if cache_hits:
            logger.info("证据卡缓存命中 %s/%s 篇，跳过重抓", cache_hits, len(out))
    return out


async def persist_evidence_backfill(
    project_id: Any,
    db: Any,
    cards: Sequence[Dict[str, Any]],
) -> None:
    """把 enrich / tier / 全文缓存回写到 literatures。按 zotero_item_key/doi/title 粗匹配。"""
    result = await db.execute(select(Literature).where(Literature.project_id == project_id))
    lits = list(result.scalars().all())
    by_key = {(x.zotero_item_key or "").strip(): x for x in lits if x.zotero_item_key}
    by_doi = {(x.doi or "").strip().lower(): x for x in lits if x.doi}
    by_title = {(x.title or "").strip().lower(): x for x in lits if x.title}
    changed = 0
    for card in cards or []:
        if not isinstance(card, dict):
            continue
        lit_changed = False
        lit = None
        zkey = (card.get("zotero_item_key") or "").strip()
        doi = (card.get("doi") or "").strip().lower()
        title = (card.get("title") or "").strip().lower()
        if zkey and zkey in by_key:
            lit = by_key[zkey]
        elif doi and doi in by_doi:
            lit = by_doi[doi]
        elif title and title in by_title:
            lit = by_title[title]
        if not lit:
            continue
        new_abs = (card.get("abstract") or "").strip() or None
        new_url = (card.get("landing_url") or "").strip() or None
        new_text = _truncate_evidence_text((card.get("evidence_text") or "").strip()) or None
        new_tier = (card.get("evidence_tier") or "").strip() or None
        new_source = (card.get("evidence_source") or "").strip() or None
        new_ckey = (card.get("evidence_content_key") or "").strip() or None
        if new_abs and not lit.abstract:
            lit.abstract = new_abs
            changed += 1
            lit_changed = True
        if new_url and not lit.landing_url:
            lit.landing_url = new_url
            changed += 1
            lit_changed = True
        if new_text and lit.evidence_text != new_text:
            lit.evidence_text = new_text
            changed += 1
            lit_changed = True
        if new_tier and lit.evidence_tier != new_tier:
            lit.evidence_tier = new_tier
            changed += 1
            lit_changed = True
        if new_source and lit.evidence_source != new_source:
            lit.evidence_source = new_source
            changed += 1
            lit_changed = True
        if new_ckey and lit.evidence_content_key != new_ckey:
            lit.evidence_content_key = new_ckey
            changed += 1
            lit_changed = True
        if lit_changed:
            lit.evidence_fetched_at = datetime.now(timezone.utc)
    if changed:
        await db.flush()
