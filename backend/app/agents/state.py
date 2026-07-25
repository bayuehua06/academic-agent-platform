"""LangGraph 学术写作工作流状态定义。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class LiteratureSource(TypedDict, total=False):
    """单篇文献在 Agent 状态中的表示。"""

    title: str
    authors: List[str]
    year: str
    doi: str
    abstract: str
    relevance_score: float
    zotero_item_key: Optional[str]


class AcademicAgentState(TypedDict, total=False):
    """
    LangGraph 全局状态。

    支持中断与恢复：可将序列化后的 state 持久化到项目记录中。
    """

    project_id: str
    assessment_requirements: str
    notebook_context: str
    keywords: List[str]
    outline: List[str]
    sources: List[LiteratureSource]
    draft_markdown: str
    apa_references: str
    max_papers: int
    skip_search: bool
    zotero_collection_id: Optional[str]
    error: Optional[str]
    current_step: str
