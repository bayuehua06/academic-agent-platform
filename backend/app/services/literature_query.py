"""Z5：按章用 LLM 生成文献检索词。"""

from __future__ import annotations

import logging
import re
from typing import Tuple

from app.services.llm_client import safe_invoke_chat
from app.services import summarizer as summarizer_module

logger = logging.getLogger(__name__)

_SYSTEM = (
    "你是学术文献检索助手。根据论文章节标题、要点与作业背景，"
    "生成一条适合 IEEE Xplore / ACM Digital Library 的英文检索式。"
    "要求：\n"
    "1. 只输出一行检索词本身，不要引号、编号或解释；\n"
    "2. 3–12 个实词，可用 AND / OR；\n"
    "3. 面向该章主题，避免过宽（如仅 technology）或过窄的专有名词堆砌；\n"
    "4. 不要编造不存在的标准编号。"
)


def suggest_chapter_query(
    *,
    heading: str,
    key_points: str = "",
    assessment_summary: str = "",
    specific_requirements: str = "",
) -> Tuple[str, str]:
    """
    为某一大纲章节生成检索词。

    Returns:
        (query, mode) — mode 为 `llm` 或 `fallback`
    """
    title = (heading or "").strip()
    if not title:
        raise ValueError("章节标题不能为空")

    points = (key_points or "").strip()
    assessment = (assessment_summary or "").strip()
    specific = (specific_requirements or "").strip()

    fallback = _fallback_query(title, points)

    if not summarizer_module.has_openai_key():
        logger.info("无 OPENAI_API_KEY，Z5 回退规则检索词 heading=%s", title)
        return fallback, "fallback"

    user = (
        f"Chapter heading: {title}\n"
        f"Key points:\n{points or '(none)'}\n\n"
        f"Assessment summary (excerpt):\n{assessment[:2500] or '(none)'}\n\n"
        f"Specific requirements (excerpt):\n{specific[:800] or '(none)'}\n"
    )
    raw = safe_invoke_chat(_SYSTEM, user, temperature=0.2, max_input=6000)
    query = _clean_query(raw) if raw else ""
    if not query:
        logger.warning("Z5 LLM 无效输出，回退规则词 heading=%s", title)
        return fallback, "fallback"
    return query, "llm"


def _clean_query(text: str) -> str:
    line = (text or "").strip().splitlines()[0].strip()
    line = re.sub(r'^[\s"\'`]+|[\s"\'`]+$', "", line)
    line = re.sub(r"^(query|search|检索词)\s*[:：]\s*", "", line, flags=re.I)
    # 去掉过长尾注
    if len(line) > 200:
        line = line[:200].rsplit(" ", 1)[0]
    return line.strip()


def _fallback_query(heading: str, key_points: str) -> str:
    """无 Key 时：标题 + 要点前若干词。"""
    blob = f"{heading} {key_points}".strip()
    words = re.findall(r"[A-Za-z][A-Za-z0-9\-]+|[\u4e00-\u9fff]{2,}", blob)
    picked = words[:8]
    if picked:
        # 中英混排时用空格连接；英文库更吃英文词
        eng = [w for w in picked if re.match(r"^[A-Za-z]", w)]
        if len(eng) >= 2:
            return " ".join(eng[:8])
        return " ".join(picked)
    return heading.strip() or "literature review"
