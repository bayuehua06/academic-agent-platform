"""Z5 检索词生成测试。"""

from app.services import literature_query as lq_module
from app.services import summarizer as summarizer_module
from app.services.literature_query import suggest_chapter_query
from tests.helpers import prepare_writing_inputs


def test_suggest_query_fallback_without_key(monkeypatch):
    monkeypatch.setattr(summarizer_module, "has_openai_key", lambda: False)
    q, mode = suggest_chapter_query(
        heading="Literature Review",
        key_points="food delivery platforms transformation",
    )
    assert mode == "fallback"
    assert "food" in q.lower() or "delivery" in q.lower() or "Literature" in q


def test_suggest_query_llm_path(monkeypatch):
    monkeypatch.setattr(summarizer_module, "has_openai_key", lambda: True)
    monkeypatch.setattr(
        lq_module,
        "safe_invoke_chat",
        lambda *a, **k: 'food delivery AND "platform transformation"',
    )
    q, mode = suggest_chapter_query(
        heading="Introduction",
        key_points="scope of digital platforms",
        assessment_summary="Write APA review",
    )
    assert mode == "llm"
    assert "food delivery" in q.lower()


async def test_suggest_query_api(auth_client, monkeypatch):
    monkeypatch.setattr(summarizer_module, "has_openai_key", lambda: True)
    monkeypatch.setattr(
        "app.api.literature_search.suggest_chapter_query",
        lambda **kwargs: ("platform economy AND gig work", "llm"),
    )
    create = await auth_client.post("/api/projects", json={"title": "Z5"})
    pid = create.json()["id"]
    await prepare_writing_inputs(auth_client, pid)
    res = await auth_client.post(
        f"/api/projects/{pid}/literature-search/suggest-query",
        json={"outline_heading": "Introduction"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["query"] == "platform economy AND gig work"
    assert body["mode"] == "llm"
