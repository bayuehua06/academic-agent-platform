"""citation_guard：禁止编造文献。"""

from app.services.citation_guard import (
    CITATION_HARD_RULES,
    build_allowed_surname_years,
    format_allowed_sources_block,
    sanitize_citations,
    verify_citations,
)


def test_citation_hard_rules_are_non_negotiable():
    assert "NON-NEGOTIABLE" in CITATION_HARD_RULES
    assert "ALLOWED SOURCES" in CITATION_HARD_RULES
    assert "ZERO in-text citations" in CITATION_HARD_RULES


def test_empty_library_forbids_all_cites():
    text = (
        "Platform work is expanding (FakeAuthor, 2019). "
        "Smith (2020) also argued otherwise. "
        "See also (Doe & Roe, 2021)."
    )
    cleaned, removed = sanitize_citations(text, [])
    assert "FakeAuthor" not in cleaned
    assert "Smith (2020)" not in cleaned
    assert "Doe" not in cleaned
    assert removed
    check = verify_citations(cleaned, [])
    assert check["ok"] is True


def test_keeps_allowed_citations_only():
    sources = [
        {
            "title": "Real Paper",
            "authors": ["Alice Real"],
            "year": "2020",
        },
        {
            "title": "Another",
            "authors": ["Bob Two", "Carol Two"],
            "year": "2021",
        },
    ]
    text = (
        "Evidence is mixed (Real, 2020; Hallucinated, 2018). "
        "Others disagree (Hallucinated, 2018). "
        "Two (2021) notes limits."
    )
    cleaned, removed = sanitize_citations(text, sources)
    assert "(Real, 2020)" in cleaned
    assert "Hallucinated" not in cleaned
    assert "Two (2021)" in cleaned
    assert any("Hallucinated" in r for r in removed)
    allowed = build_allowed_surname_years(sources)
    assert ("real", "2020") in allowed
    assert ("two", "2021") in allowed


def test_allowed_sources_block_empty():
    block = format_allowed_sources_block([])
    assert "NONE" in block
    assert "out-of-library" in block
    assert "forbidden" in block


def test_allowed_sources_block_lists_forms():
    block = format_allowed_sources_block(
        [{"title": "T", "authors": ["Jane Doe"], "year": "2019"}]
    )
    assert "(Doe, 2019)" in block
    assert "ALLOWED SOURCES" in block
