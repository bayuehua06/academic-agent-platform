"""LangGraph 学术写作工作流组装。"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.agents.nodes.apa_formatter import format_apa_references
from app.agents.nodes.requirement_analyzer import analyze_requirements
from app.agents.nodes.researcher import search_literature
from app.agents.nodes.writer import write_apa_draft
from app.agents.state import AcademicAgentState, OutlineSection

logger = logging.getLogger(__name__)


def _build_graph():
    """构建带线性节点与状态传递的 StateGraph。"""
    try:
        from langgraph.graph import END, StateGraph
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("请安装 langgraph: pip install langgraph") from exc

    graph = StateGraph(AcademicAgentState)
    graph.add_node("analyze_requirements", analyze_requirements)
    graph.add_node("search_literature", search_literature)
    graph.add_node("write_apa_draft", write_apa_draft)
    graph.add_node("format_apa_references", format_apa_references)

    graph.set_entry_point("analyze_requirements")
    graph.add_edge("analyze_requirements", "search_literature")
    graph.add_edge("search_literature", "write_apa_draft")
    graph.add_edge("write_apa_draft", "format_apa_references")
    graph.add_edge("format_apa_references", END)

    return graph.compile()


_compiled_graph = None


def get_academic_graph():
    """获取（或编译）学术 Agent 图。"""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = _build_graph()
    return _compiled_graph


def run_academic_workflow(
    project_id: str,
    assessment_summary: str = "",
    paper_outline: Optional[List[OutlineSection]] = None,
    specific_requirements: str = "",
    background_summaries: Optional[List[str]] = None,
    *,
    # 兼容旧参数
    assessment_requirements: str = "",
    notebook_context: str = "",
    max_papers: int = 5,
    skip_search: bool = False,
    zotero_collection_id: Optional[str] = None,
    existing_sources: Optional[list] = None,
    section_directives: Optional[list] = None,
    confirmed_facts: str = "",
) -> AcademicAgentState:
    """
    执行完整学术写作工作流。

    优先使用定稿字段；旧参数 assessment_requirements / notebook_context 仍可用。
    """
    assessment = (assessment_summary or assessment_requirements or "").strip()
    backgrounds = list(background_summaries or [])
    if not backgrounds and notebook_context:
        backgrounds = [notebook_context]

    initial: AcademicAgentState = {
        "project_id": project_id,
        "assessment_summary": assessment,
        "paper_outline": paper_outline or [],
        "specific_requirements": specific_requirements or "",
        "background_summaries": backgrounds,
        "assessment_requirements": assessment,
        "notebook_context": "\n\n".join(backgrounds),
        "keywords": [],
        "outline": [],
        "sources": existing_sources or [],
        "draft_markdown": "",
        "apa_references": "",
        "max_papers": max_papers,
        "skip_search": skip_search,
        "zotero_collection_id": zotero_collection_id,
        "section_directives": list(section_directives or []),
        "confirmed_facts": confirmed_facts or "",
        "error": None,
        "current_step": "start",
    }

    graph = get_academic_graph()
    logger.info("启动 LangGraph 工作流 project_id=%s", project_id)
    result: Dict[str, Any] = graph.invoke(initial)
    return AcademicAgentState(**result)


def run_workflow_stepwise(state: AcademicAgentState) -> AcademicAgentState:
    """无 LangGraph 时的降级顺序执行（便于测试与中断恢复）。"""
    state = analyze_requirements(state)
    state = search_literature(state)
    state = write_apa_draft(state)
    state = format_apa_references(state)
    return state
