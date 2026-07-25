"""NotebookLM 同步服务（MVP 粘贴 + 预留 Playwright 抓取）。"""

from __future__ import annotations

import logging
import re
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class NotebookLMService:
    """解析 NotebookLM 输入，提取摘要与约束要点。"""

    def extract_summary(self, raw_transcript: str, max_chars: int = 2000) -> str:
        """
        MVP：从粘贴的对话/笔记中提取要点摘要。

        策略：取前若干非空段落，并标注以 Constraint/Requirement 开头的行。
        """
        if not raw_transcript or not raw_transcript.strip():
            return ""

        lines = [ln.strip() for ln in raw_transcript.splitlines() if ln.strip()]
        constraints = [
            ln
            for ln in lines
            if re.match(r"^(constraint|requirement|必须|要求|约束)[:：\s]", ln, re.I)
        ]
        body = lines[:30]
        parts = []
        if constraints:
            parts.append("## Constraints\n" + "\n".join(f"- {c}" for c in constraints[:10]))
        parts.append("## Transcript Highlights\n" + "\n".join(body))
        summary = "\n\n".join(parts)
        return summary[:max_chars]

    def parse_markdown_file(self, content: str) -> Tuple[str, str]:
        """解析上传的 Markdown，返回 (raw_transcript, extracted_summary)。"""
        summary = self.extract_summary(content)
        return content, summary

    async def fetch_via_browser(self, notebook_url: str) -> Optional[str]:
        """
        扩展模式：使用 browser-use / Playwright 抓取 NotebookLM 对话。

        当前为桩实现，配置 Chrome Profile 后可接入真实抓取。
        """
        logger.info("NotebookLM browser sync 预留接口被调用: %s", notebook_url)
        # TODO: 接入 browser-use + 已登录 Chrome Profile
        # from browser_use import Agent
        raise NotImplementedError(
            "Playwright/browser-use 自动抓取尚未启用，请使用手动粘贴或 Markdown 上传"
        )


notebooklm_service = NotebookLMService()
