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
