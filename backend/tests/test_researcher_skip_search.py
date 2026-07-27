"""researcher：skip_search 空库不得注入 mock 文献。"""

from app.agents.nodes.researcher import search_literature


def test_skip_search_with_empty_sources_does_not_mock():
    state = {
        "project_id": "p1",
        "keywords": ["agile"],
        "paper_outline": [{"level": 1, "heading": "Introduction", "key_points": ""}],
        "sources": [],
        "skip_search": True,
        "max_papers": 5,
        "zotero_collection_id": None,
    }
    out = search_literature(state)
    assert out["sources"] == []
    assert out["current_step"] == "search_literature"


def test_skip_search_keeps_existing_sources():
    existing = [
        {
            "title": "Real Paper",
            "authors": ["Doe, J."],
            "year": "2021",
            "doi": "10.1/x",
            "abstract": "",
            "relevance_score": 1.0,
            "zotero_item_key": "ABC",
        }
    ]
    out = search_literature(
        {
            "project_id": "p1",
            "keywords": [],
            "paper_outline": [],
            "sources": existing,
            "skip_search": True,
            "max_papers": 5,
        }
    )
    assert len(out["sources"]) == 1
    assert out["sources"][0]["title"] == "Real Paper"


def test_without_skip_search_still_can_mock(monkeypatch):
    """非 skip 路径仍可 mock（仅供旧联调）；确认行为未静默改错。"""
    called = {"n": 0}

    def _fake_mock(keywords, max_papers):
        called["n"] += 1
        return [
            {
                "title": "Mock",
                "authors": ["Smith, J."],
                "year": "2020",
                "doi": "10.x",
                "abstract": "",
                "relevance_score": 0.9,
                "zotero_item_key": None,
            }
        ]

    monkeypatch.setattr(
        "app.agents.nodes.researcher._search_with_browser",
        _fake_mock,
    )
    monkeypatch.setattr(
        "app.agents.nodes.researcher._sync_zotero",
        lambda sources, _cid: sources,
    )
    out = search_literature(
        {
            "project_id": "p1",
            "keywords": ["agile"],
            "paper_outline": [],
            "sources": [],
            "skip_search": False,
            "max_papers": 3,
        }
    )
    assert called["n"] == 1
    assert out["sources"][0]["authors"] == ["Smith, J."]
