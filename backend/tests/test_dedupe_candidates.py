"""文献候选去重单元测试。"""

from app.services.literature_workflow import dedupe_candidates


def test_dedupe_by_doi_keeps_first():
    rows = [
        {"title": "A", "doi": "10.1/x", "provider": "ieee"},
        {"title": "A copy", "doi": "10.1/X", "provider": "acm"},
    ]
    out = dedupe_candidates(rows)
    assert len(out) == 1
    assert out[0]["provider"] == "ieee"


def test_dedupe_by_title_when_no_doi():
    rows = [
        {"title": "Same Title", "doi": None, "provider": "ieee"},
        {"title": "  same   title ", "doi": "", "provider": "acm"},
        {"title": "Other", "provider": "acm"},
    ]
    out = dedupe_candidates(rows)
    assert [r["title"] for r in out] == ["Same Title", "Other"]
