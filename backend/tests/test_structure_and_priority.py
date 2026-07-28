"""结构保真、must_apply、字数容差相关测试。"""

from app.services.structure_guard import (
    extract_seed_tables,
    key_points_has_table,
    verify_outline_structure,
)
from app.services.writing_constraints import (
    WritingConstraints,
    bind_must_apply_documents,
    extract_must_apply_rule_based,
    extract_writing_constraints,
    verify_draft_against_constraints,
)
from app.services import summarizer as summarizer_module


def test_table_seed_hint_requires_english_rewrite():
    from app.services.structure_guard import format_table_seed_hint

    kp = (
        "比较方案：\n"
        "| 维度 | 方案A | 方案B |\n"
        "|------|-------|-------|\n"
        "| 成本 | 较低 | 较高 |\n"
    )
    hint = format_table_seed_hint(kp)
    assert "STRUCTURE HARD RULE" in hint
    assert "academic English" in hint
    assert "TRANSLATE" in hint or "translate" in hint.lower()
    assert "不要" not in hint or "Chinese" in hint
    assert "方案A" in hint  # seed 仍注入供模型翻译
    assert "verbatim" in hint.lower() or "do NOT copy Chinese" in hint


def test_key_points_table_detection():
    kp = (
        "Fill the comparison:\n"
        "| Criterion | Proposal A | Proposal B |\n"
        "|-----------|------------|------------|\n"
        "| Cost |  |  |\n"
    )
    assert key_points_has_table(kp) is True
    assert len(extract_seed_tables(kp)) >= 1
    assert key_points_has_table("Just discuss platforms.") is False


def test_verify_outline_flags_missing_table():
    outline = [
        {
            "level": 1,
            "heading": "Evaluation",
            "key_points": (
                "| Metric | Score |\n"
                "|--------|-------|\n"
                "| Cost |  |\n"
            ),
        }
    ]
    draft_no_table = "# Evaluation\n\nWe discuss cost narratively only.\n"
    v = verify_outline_structure(draft_no_table, outline)
    assert v["ok"] is False
    assert "Evaluation" in v["missing_tables"]

    draft_ok = (
        "# Evaluation\n\n"
        "| Metric | Score |\n"
        "|--------|-------|\n"
        "| Cost | High |\n"
    )
    v2 = verify_outline_structure(draft_ok, outline)
    assert v2["ok"] is True


def test_must_apply_rule_and_bind(monkeypatch):
    monkeypatch.setattr(summarizer_module, "has_openai_key", lambda: False)
    specs = extract_must_apply_rule_based(
        "You must follow the document Platform Rubric Guide for scoring."
    )
    assert specs
    matched, unmatched = bind_must_apply_documents(
        specs,
        [
            {
                "title": "Platform Rubric Guide",
                "role": "BACKGROUND",
                "summary_text": "Use four criteria: cost, risk, fit, feasibility.",
                "raw_text": "",
            }
        ],
    )
    assert matched
    assert matched[0]["title"] == "Platform Rubric Guide"
    assert unmatched == []

    c = extract_writing_constraints(
        specific="Must apply document Platform Rubric Guide. 800-1000 English words.",
        assessment="Marking criteria include critical analysis.",
    )
    assert c.source == "fallback"
    block = c.to_prompt_block()
    assert "Assessment" in block or "grading" in block.lower()
    assert "800" in block or "1000" in block


def test_verify_word_count_tighter_high():
    c = WritingConstraints(word_min=100, word_max=120)
    # 超过 max*1.1
    long = "word " * 200
    v = verify_draft_against_constraints(long, c)
    assert v["ok"] is False
    assert any("too high" in i.lower() for i in v["issues"])


def test_force_section_heading_strips_wrong_titles():
    from app.services.structure_guard import force_section_heading

    body = (
        "# Academic Draft\n\n"
        "# Research Design\n\n"
        "Body about methods stays.\n"
    )
    out = force_section_heading(body, heading="Methods", level=2)
    assert out.startswith("## Methods\n")
    assert "Academic Draft" not in out
    assert "Research Design" not in out
    assert "Body about methods stays." in out


def test_rebuild_draft_to_outline_restores_missing_heading_and_table():
    from app.services.structure_guard import rebuild_draft_to_outline

    outline = [
        {"level": 1, "heading": "Introduction", "key_points": "scope"},
        {
            "level": 1,
            "heading": "Evaluation",
            "key_points": (
                "| Metric | Score |\n"
                "|--------|-------|\n"
                "| Cost |  |\n"
            ),
        },
    ]
    messy = (
        "# Academic Draft\n\n"
        "# Intro Remixed\n\n"
        "Hello.\n\n"
        "# Evaluation\n\n"
        "Narrative only, no table.\n"
    )
    fixed = rebuild_draft_to_outline(messy, outline)
    assert "# Introduction" in fixed
    assert "# Evaluation" in fixed
    assert "Academic Draft" not in fixed
    assert "Intro Remixed" not in fixed
    assert "| Metric | Score |" in fixed
    v = verify_outline_structure(fixed, outline)
    assert v["ok"] is True
    assert v["missing_headings"] == []
    assert v["missing_tables"] == []


def test_rebuild_does_not_duplicate_nested_subsections():
    """父节 span 不得吞子节后再按大纲追加——否则会×2；二次 rebuild 会×3。"""
    from app.services.structure_guard import rebuild_draft_to_outline

    outline = [
        {"level": 1, "heading": "Chapter 5", "key_points": "intro"},
        {"level": 2, "heading": "5.1 Methods", "key_points": "m"},
        {"level": 2, "heading": "5.2 Results", "key_points": "r"},
        {"level": 1, "heading": "Chapter 6", "key_points": "c6"},
    ]
    draft = (
        "# Chapter 5\n\n"
        "Parent intro.\n\n"
        "## 5.1 Methods\n\n"
        "Methods body.\n\n"
        "## 5.2 Results\n\n"
        "Results body.\n\n"
        "# Chapter 6\n\n"
        "Chapter six body.\n"
    )
    once = rebuild_draft_to_outline(draft, outline)
    twice = rebuild_draft_to_outline(once, outline)
    assert once.lower().count("## 5.1 methods") == 1
    assert once.lower().count("## 5.2 results") == 1
    assert twice.lower().count("## 5.1 methods") == 1
    assert twice == once
    assert "Parent intro." in once
    assert "Methods body." in once
    assert "Results body." in once


def test_strip_nested_outline_headings_removes_child_blocks():
    from app.services.structure_guard import strip_nested_outline_headings

    body = (
        "Parent only.\n\n"
        "## 5.1 Methods\n\n"
        "Should drop.\n\n"
        "Still parent? no — inside child.\n"
    )
    out = strip_nested_outline_headings(
        body,
        ["Chapter 5", "5.1 Methods", "5.2 Results"],
        keep_heading="Chapter 5",
    )
    assert "Parent only." in out
    assert "5.1 Methods" not in out
    assert "Should drop." not in out


def test_format_verification_issues_for_changelog():
    from app.services.structure_guard import format_verification_issues_for_changelog

    text = format_verification_issues_for_changelog(
        {
            "ok": False,
            "issues": ["Missing outline headings in draft: Methods"],
            "structure": {
                "missing_headings": ["Methods"],
                "missing_tables": ["Evaluation"],
            },
            "missing_must_include": ["critical reflection"],
            "citation_ok": False,
            "hallucinated_citations": ["(Ghost, 1999)"],
        }
    )
    assert "issues=" in text
    assert "missing_headings=Methods" in text
    assert "missing_tables=Evaluation" in text
    assert "missing_must_include=critical reflection" in text
    assert "Ghost" in text

