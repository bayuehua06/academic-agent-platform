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
    landing_url: str
    evidence_text: str
    evidence_tier: str
    evidence_source: str
    evidence_content_key: str
    relevance_score: float
    zotero_item_key: Optional[str]
    assigned_headings: List[str]


class OutlineSection(TypedDict, total=False):
    """锁定后的论文大纲节。"""

    level: int
    heading: str
    key_points: str


class AcademicAgentState(TypedDict, total=False):
    """
    LangGraph 全局状态。

    定稿输入：assessment_summary / paper_outline / specific_requirements /
    background_summaries。兼容旧字段 assessment_requirements / notebook_context。
    """

    project_id: str
    assessment_summary: str
    paper_outline: List[OutlineSection]
    specific_requirements: str
    background_summaries: List[str]
    # 兼容旧调用
    assessment_requirements: str
    notebook_context: str
    keywords: List[str]
    outline: List[str]
    sources: List[LiteratureSource]
    draft_markdown: str
    apa_references: str
    writer_mode: str  # llm | template
    writer_model: Optional[str]
    writer_word_count: int
    writer_word_target: Dict[str, int]
    writer_constraints: Dict[str, Any]
    writer_verification: Dict[str, Any]
    writer_auto_repair: bool
    max_papers: int
    skip_search: bool
    zotero_collection_id: Optional[str]
    error: Optional[str]
    current_step: str
    # P3/M4：确认后的章节指令与跨节 Facts
    section_directives: List[Dict[str, Any]]
    confirmed_facts: str
    # 项目源文档目录（供 must_apply 绑定）
    available_documents: List[Dict[str, Any]]
