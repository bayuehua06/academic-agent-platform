"""共享 OpenAI Chat 调用（Summarizer / Z5 / Writer）。"""

from __future__ import annotations

import logging
from typing import Literal, Optional

from app.core.config import get_settings
from app.services import summarizer as summarizer_module

logger = logging.getLogger(__name__)
settings = get_settings()

ModelPurpose = Literal["default", "writer"]


def resolve_model(purpose: ModelPurpose = "default") -> str:
    """解析实际模型名。"""
    if purpose == "writer":
        writer = (settings.openai_writer_model or "").strip()
        if writer:
            return writer
    return (settings.openai_model or "gpt-4o-mini").strip() or "gpt-4o-mini"


def invoke_chat(
    system: str,
    user: str,
    *,
    temperature: float = 0.3,
    max_input: int = 14000,
    max_tokens: Optional[int] = None,
    purpose: ModelPurpose = "default",
) -> str:
    """
    调用 ChatOpenAI；调用方需先确认 has_openai_key()。

    Raises:
        RuntimeError: 未配置 Key 或调用失败
    """
    if not summarizer_module.has_openai_key():
        raise RuntimeError("未配置 OPENAI_API_KEY")

    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    model = resolve_model(purpose)
    kwargs = {
        "api_key": settings.openai_api_key,
        "model": model,
        "temperature": temperature,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    llm = ChatOpenAI(**kwargs)
    resp = llm.invoke(
        [
            SystemMessage(content=system),
            HumanMessage(content=(user or "")[:max_input]),
        ]
    )
    text = (getattr(resp, "content", None) or str(resp) or "").strip()
    if not text:
        raise RuntimeError("LLM 返回空内容")
    return text


def safe_invoke_chat(
    system: str,
    user: str,
    *,
    temperature: float = 0.3,
    max_input: int = 14000,
    max_tokens: Optional[int] = None,
    purpose: ModelPurpose = "default",
) -> Optional[str]:
    """调用 LLM；失败返回 None。"""
    try:
        return invoke_chat(
            system,
            user,
            temperature=temperature,
            max_input=max_input,
            max_tokens=max_tokens,
            purpose=purpose,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM 调用失败 (purpose=%s): %s", purpose, exc)
        return None
