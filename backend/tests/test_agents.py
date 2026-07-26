"""LangGraph Agent 节点单元测试（不依赖数据库）。"""

from app.agents.graph import run_workflow_stepwise, get_academic_graph
from app.agents.nodes.apa_formatter import format_apa_reference, format_apa_references
from app.agents.nodes.requirement_analyzer import analyze_requirements
from app.agents.nodes.writer import format_intext_citation, write_apa_draft
from app.agents.state import AcademicAgentState, LiteratureSource
from app.services import summarizer as summarizer_module


def test_intext_citation_single_double_etal():
    assert format_intext_citation(["Smith, J."], "2024") == "(Smith, 2024)"
    assert format_intext_citation(["Zhang, W.", "Li, Y."], "2024") == "(Zhang & Li, 2024)"
    assert (
        format_intext_citation(["Wang, H.", "Chen, L.", "Liu, M."], "2023")
        == "(Wang et al., 2023)"
    )


def test_analyze_requirements_extracts_keywords_and_outline():
    state = AcademicAgentState(
        project_id="p1",
        assessment_requirements='Write about "machine learning" in higher education.',
        notebook_context="Constraint: include ethics. 案例研究 required.",
    )
    out = analyze_requirements(state)
    assert out["keywords"]
    assert "Introduction" in out["outline"]
    assert out["current_step"] == "analyze_requirements"


def test_apa_reference_formatting_and_sort():
    sources = [
        LiteratureSource(
            title="Zebra Studies",
            authors=["Young, A."],
            year="2021",
            doi="10.1000/z",
        ),
        LiteratureSource(
            title="Alpha Methods",
            authors=["Adams, B."],
            year="2020",
            doi="10.1000/a",
        ),
    ]
    state = AcademicAgentState(project_id="p1", sources=sources)
    out = format_apa_references(state)
    refs = out["apa_references"]
    assert "Adams" in refs
    assert "Young" in refs
    # 姓氏排序：Adams 应出现在 Young 之前
    assert refs.index("Adams") < refs.index("Young")
    assert "*Alpha Methods*" in refs


def test_write_apa_draft_follows_paper_outline_levels(monkeypatch):
    monkeypatch.setattr(summarizer_module, "has_openai_key", lambda: False)
    state = AcademicAgentState(
        project_id="p1",
        paper_outline=[
            {"level": 1, "heading": "Introduction", "key_points": "scope"},
            {"level": 2, "heading": "Methods Detail", "key_points": ""},
        ],
        sources=[
            LiteratureSource(
                title="Sample Paper",
                authors=["Smith, J."],
                year="2024",
            )
        ],
        keywords=["AI"],
        assessment_summary="APA ethics",
    )
    out = write_apa_draft(state)
    md = out["draft_markdown"]
    assert out.get("writer_mode") == "template"
    assert "# Introduction" in md
    assert "## Methods Detail" in md
    assert "(Smith, 2024)" in md


def test_analyze_uses_locked_paper_outline():
    state = AcademicAgentState(
        project_id="p1",
        assessment_summary='Write about "machine learning".',
        paper_outline=[
            {"level": 1, "heading": "Custom Intro", "key_points": ""},
            {"level": 1, "heading": "Custom End", "key_points": ""},
        ],
        specific_requirements="Use APA",
        background_summaries=["Notes on tutoring"],
    )
    out = analyze_requirements(state)
    assert out["outline"] == ["Custom Intro", "Custom End"]
    assert out["paper_outline"][0]["heading"] == "Custom Intro"


def test_workflow_stepwise_end_to_end(monkeypatch):
    monkeypatch.setattr(summarizer_module, "has_openai_key", lambda: False)
    state = AcademicAgentState(
        project_id="p1",
        assessment_requirements="Literature review on education technology.",
        notebook_context="Constraint: undergraduate audience.",
        max_papers=2,
        skip_search=False,
    )
    result = run_workflow_stepwise(state)
    assert result["current_step"] == "format_apa_references"
    assert len(result["sources"]) == 2
    assert result["draft_markdown"]
    assert result["apa_references"]


def test_langgraph_compile_and_invoke(monkeypatch):
    monkeypatch.setattr(summarizer_module, "has_openai_key", lambda: False)
    graph = get_academic_graph()
    result = graph.invoke(
        {
            "project_id": "p2",
            "assessment_requirements": "APA review on AI ethics",
            "notebook_context": "",
            "keywords": [],
            "outline": [],
            "sources": [],
            "draft_markdown": "",
            "apa_references": "",
            "max_papers": 2,
            "skip_search": False,
            "zotero_collection_id": None,
            "error": None,
            "current_step": "start",
        }
    )
    assert result["current_step"] == "format_apa_references"
    assert len(result["sources"]) == 2


def test_single_apa_reference_contains_doi_url():
    src = LiteratureSource(
        title="Title Here",
        authors=["Smith, John"],
        year="2024",
        doi="10.1000/abc",
    )
    ref = format_apa_reference(src)
    assert "https://doi.org/10.1000/abc" in ref
    assert "*Title Here*" in ref
