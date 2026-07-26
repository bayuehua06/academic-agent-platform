"""文档摘要服务：有 OPENAI_API_KEY 时用 gpt-4o-mini；否则直存原文以便跑通。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from app.core.config import get_settings
from app.db.models import ProjectSourceDocument
from app.services.document_ingest import sanitize_extracted_text

logger = logging.getLogger(__name__)
settings = get_settings()

# 送入 LLM 的原文上限，避免超长
_LLM_INPUT_MAX = 12000


def has_openai_key() -> bool:
    return bool((settings.openai_api_key or "").strip())


_ROLE_PROMPTS = {
    "ASSESSMENT": (
        "You are an academic writing assistant. Compress the following Assessment / Rubric "
        "into a clear summary. Keep grading criteria, length/format rules, required questions, "
        "and hard constraints. Write in the SAME language as the source text (do not translate). "
        "Do not invent content."
    ),
    "BACKGROUND": (
        "You are an academic writing assistant. Compress the following background material "
        "(notes/dialogue/excerpts) into key points. Keep citable claims, definitions, and facts. "
        "Write in the SAME language as the source text. Do not invent content."
    ),
    "SPECIFIC": (
        "You are an academic writing assistant. Distill the following writing requirements into "
        "short bullets (word count, citation style, must-include/avoid, language, etc.). "
        "Write in the SAME language as the source text. Do not invent content."
    ),
    "OUTLINE": (
        "You are an academic writing assistant. Compress each section's key_points while keeping "
        "the existing heading structure. Still use Markdown headings like `## Title`. "
        "Keep the same language as the source. Do not invent new sections."
    ),
}


class SummarizerService:
    """按 role 生成 summary_text；无 API Key 时直存 content。"""

    def summarize_text(self, role: str, raw_text: str) -> tuple[str, str]:
        """
        返回 (summary_text, mode)，mode 为 `llm` 或 `passthrough`。
        """
        text = sanitize_extracted_text(raw_text or "").strip()
        if not text:
            return "", "passthrough"

        if not has_openai_key():
            logger.info("OPENAI_API_KEY 为空，role=%s 直存原文为摘要", role)
            return text, "passthrough"

        try:
            summary = self._call_llm(role, text)
            if summary.strip():
                return summary.strip(), "llm"
            logger.warning("LLM 返回空摘要，回退直存原文 role=%s", role)
            return text, "passthrough"
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM 摘要失败，回退直存原文 role=%s: %s", role, exc)
            return text, "passthrough"

    def merge_assessment_parts(self, parts: List[str]) -> str:
        """合并多条 A 摘要；无 Key 或单条时直接拼接。"""
        cleaned = [p.strip() for p in parts if p and p.strip()]
        if not cleaned:
            return ""
        if len(cleaned) == 1 or not has_openai_key():
            return "\n\n---\n\n".join(cleaned)

        joined = "\n\n---\n\n".join(cleaned)
        try:
            prompt = (
                "请将下列多份 Assessment 摘要合并为一份定稿摘要，去重并保留全部关键要求。\n\n"
                f"{joined[:_LLM_INPUT_MAX]}"
            )
            from langchain_core.messages import HumanMessage, SystemMessage
            from langchain_openai import ChatOpenAI

            llm = ChatOpenAI(
                api_key=settings.openai_api_key,
                model=settings.openai_model or "gpt-4o-mini",
                temperature=0.2,
            )
            resp = llm.invoke(
                [
                    SystemMessage(content="You are an academic writing assistant. Output only the merged summary body in the same language as the inputs."),

                    HumanMessage(content=prompt),
                ]
            )
            content = getattr(resp, "content", None) or str(resp)
            return (content or "").strip() or joined
        except Exception as exc:  # noqa: BLE001
            logger.warning("A 合并摘要失败，回退拼接: %s", exc)
            return joined

    def apply_to_document(self, doc: ProjectSourceDocument) -> str:
        """
        对已解析文档写 summary_text，并标记 SUMMARIZED。
        OUTLINE：保留 summary_json；摘要为各节要点拼接或 LLM 压缩说明。
        返回 mode: llm | passthrough。
        """
        role = (doc.role or "").upper()
        raw = doc.raw_text or ""

        if role == "OUTLINE":
            outline_blob = self._outline_as_text(doc)
            source = outline_blob or raw
            summary, mode = self.summarize_text("OUTLINE", source)
            doc.summary_text = summary or source
            # 无 Key 时不改动已解析的 heading 树；有 Key 时仍以 header 解析结果为准
            if doc.summary_json and isinstance(doc.summary_json, list):
                pass
            doc.status = "SUMMARIZED" if doc.summary_json else doc.status
            if doc.status == "FAILED":
                return mode
            doc.status = "SUMMARIZED"
            doc.summarized_at = datetime.now(timezone.utc)
            doc.error_message = None
            doc.updated_at = datetime.now(timezone.utc)
            return mode

        summary, mode = self.summarize_text(role, raw)
        doc.summary_text = summary
        doc.status = "SUMMARIZED"
        doc.summarized_at = datetime.now(timezone.utc)
        doc.error_message = None
        doc.updated_at = datetime.now(timezone.utc)
        return mode

    def _call_llm(self, role: str, text: str) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI

        system = _ROLE_PROMPTS.get(role, _ROLE_PROMPTS["BACKGROUND"])
        llm = ChatOpenAI(
            api_key=settings.openai_api_key,
            model=settings.openai_model or "gpt-4o-mini",
            temperature=0.2,
        )
        resp = llm.invoke(
            [
                SystemMessage(content=system),
                HumanMessage(content=text[:_LLM_INPUT_MAX]),
            ]
        )
        return (getattr(resp, "content", None) or str(resp) or "").strip()

    @staticmethod
    def _outline_as_text(doc: ProjectSourceDocument) -> str:
        outline = doc.summary_json
        if not isinstance(outline, list) or not outline:
            return ""
        lines: list[str] = []
        for item in outline:
            if not isinstance(item, dict):
                continue
            level = int(item.get("level") or 1)
            heading = (item.get("heading") or "").strip()
            points = (item.get("key_points") or "").strip()
            if not heading:
                continue
            lines.append(f"{'#' * max(1, min(level, 6))} {heading}")
            if points:
                lines.append(points)
            lines.append("")
        return "\n".join(lines).strip()


summarizer_service = SummarizerService()
