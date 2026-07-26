"""写作约束抽取 / 校验与 Writer 分节测试。"""

from app.agents.nodes.writer import allocate_section_words, write_apa_draft
from app.agents.state import AcademicAgentState, LiteratureSource
from app.services import summarizer as summarizer_module
from app.services import writing_constraints as wc_module
from app.services.llm_client import resolve_model
from app.services.writing_constraints import (
    WritingConstraints,
    count_words,
    extract_writing_constraints,
    parse_word_target,
    verify_draft_against_constraints,
)


def test_parse_word_target_range():
    lo, hi = parse_word_target("Word count: 4000-5000 English words. Use APA.")
    assert lo == 4000
    assert hi == 5000


def test_fallback_constraints_keeps_verbatim_d(monkeypatch):
    monkeypatch.setattr(summarizer_module, "has_openai_key", lambda: False)
    c = extract_writing_constraints(
        specific="Use APA 7th. Include critical reflection. 4000-5000 English words.",
        assessment="Literature review assignment",
    )
    assert c.source == "fallback"
    assert c.word_min == 4000
    block = c.to_prompt_block()
    assert "APA" in block
    assert "critical reflection" in c.raw_specific.lower()


def test_verify_flags_missing_must_include():
    c = WritingConstraints(
        must_include=["digital platforms transformation"],
        word_min=100,
        word_max=500,
        raw_specific="must discuss digital platforms transformation",
    )
    short = "# Intro\n\nHello world only."
    v = verify_draft_against_constraints(short, c)
    assert v["ok"] is False
    assert v["missing_must_include"]


def test_resolve_writer_model(monkeypatch):
    from app.services import llm_client as lc

    monkeypatch.setattr(lc.settings, "openai_model", "gpt-4o-mini")
    monkeypatch.setattr(lc.settings, "openai_writer_model", "gpt-4o")
    assert resolve_model("writer") == "gpt-4o"
    assert resolve_model("default") == "gpt-4o-mini"


def test_allocate_section_words_sums_near_mid():
    sections = [
        {"level": 1, "heading": "Introduction", "key_points": ""},
        {"level": 1, "heading": "Literature", "key_points": "a"},
        {"level": 1, "heading": "Discussion", "key_points": "b"},
        {"level": 1, "heading": "Conclusion", "key_points": ""},
    ]
    budgets = allocate_section_words(sections, 4000, 5000)
    assert len(budgets) == 4
    assert abs(sum(budgets) - 4500) < 200


def test_write_apa_draft_template_when_no_key(monkeypatch):
    monkeypatch.setattr(summarizer_module, "has_openai_key", lambda: False)
    state = AcademicAgentState(
        project_id="p1",
        paper_outline=[
            {"level": 1, "heading": "Introduction", "key_points": "scope"},
            {"level": 2, "heading": "Methods Detail", "key_points": ""},
        ],
        sources=[
            LiteratureSource(title="Sample Paper", authors=["Smith, J."], year="2024")
        ],
        keywords=["AI"],
        assessment_summary="APA ethics",
        specific_requirements="4000-5000 English words. Include critical reflection.",
    )
    out = write_apa_draft(state)
    assert out["writer_mode"] == "template"
    assert "# Introduction" in out["draft_markdown"]
    assert out["writer_word_target"]["min"] == 4000


def test_write_section_prompts_include_constraints(monkeypatch):
    monkeypatch.setattr(summarizer_module, "has_openai_key", lambda: True)
    seen = {"write_has_constraints": False, "expand_has_constraints": False}

    def fake_chat(system, user, **kwargs):  # noqa: ANN001
        if "extract HARD writing constraints" in system:
            return (
                '{"checklist":["Use APA 7th","Include critical reflection"],'
                '"word_min":800,"word_max":1000,"citation_style":"APA 7th",'
                '"language":"English","must_include":["critical reflection"],'
                '"must_avoid":[],"other_notes":""}'
            )
        if "HARD CONSTRAINTS" in user:
            if "Section to expand" in user:
                seen["expand_has_constraints"] = True
            if "TARGET FOR THIS SECTION" in user:
                seen["write_has_constraints"] = True
        if "TARGET FOR THIS SECTION" in user:
            if "Introduction" in user:
                return (
                    "# Introduction\n\n"
                    + ("Platforms and critical reflection (Smith, 2024). " * 50)
                )
            return (
                "## Methods Detail\n\n"
                + ("Methods with critical reflection (Smith, 2024). " * 50)
            )
        if "Unmet issues" in user or "revise an academic" in system.lower():
            return user.split("Current draft:\n", 1)[-1]
        if "Section to expand" in user:
            return user.split("Section to expand:\n", 1)[-1]
        return "# X\n\nbody"

    monkeypatch.setattr("app.agents.nodes.writer.safe_invoke_chat", fake_chat)
    monkeypatch.setattr(wc_module, "safe_invoke_chat", fake_chat)

    state = AcademicAgentState(
        project_id="p1",
        paper_outline=[
            {"level": 1, "heading": "Introduction", "key_points": "scope"},
            {"level": 2, "heading": "Methods Detail", "key_points": "design"},
        ],
        sources=[
            LiteratureSource(
                title="Sample Paper",
                authors=["Smith, J."],
                year="2024",
                abstract="About platforms.",
            )
        ],
        assessment_summary="APA ethics",
        specific_requirements="800-1000 English words. APA 7th. Include critical reflection.",
    )
    out = write_apa_draft(state)
    assert out["writer_mode"] == "llm"
    assert seen["write_has_constraints"] is True
    assert out["writer_constraints"]["source"] == "llm"
    assert "writer_verification" in out
    assert count_words(out["draft_markdown"]) == out["writer_word_count"]
