"""Summarizer 服务与 API：无 Key 直存；有 Key 时 mock LLM。"""

from __future__ import annotations

from app.services import summarizer as summarizer_module
from app.services.summarizer import SummarizerService, summarizer_service


def test_passthrough_when_no_api_key(monkeypatch):
    monkeypatch.setattr(summarizer_module, "has_openai_key", lambda: False)
    text = "Write an APA literature review on tutoring."
    summary, mode = SummarizerService().summarize_text("ASSESSMENT", text)
    assert mode == "passthrough"
    assert summary == text


def test_llm_path_when_key_present(monkeypatch):
    monkeypatch.setattr(summarizer_module, "has_openai_key", lambda: True)

    class _Resp:
        content = "压缩后的评估摘要"

    class _FakeLLM:
        def invoke(self, _messages):  # noqa: ANN001
            return _Resp()

    svc = SummarizerService()
    monkeypatch.setattr(svc, "_call_llm", lambda role, text: "压缩后的评估摘要")
    summary, mode = svc.summarize_text("ASSESSMENT", "很长的 rubric 原文 " * 20)
    assert mode == "llm"
    assert summary == "压缩后的评估摘要"


def test_merge_assessment_passthrough(monkeypatch):
    monkeypatch.setattr(summarizer_module, "has_openai_key", lambda: False)
    merged = summarizer_service.merge_assessment_parts(["A1", "A2"])
    assert "A1" in merged and "A2" in merged


async def test_ingest_sets_summarized_without_key(auth_client, monkeypatch):
    monkeypatch.setattr(summarizer_module, "has_openai_key", lambda: False)
    create = await auth_client.post("/api/projects", json={"title": "Sum"})
    pid = create.json()["id"]
    raw = "Full assessment content for passthrough storage."
    res = await auth_client.post(
        f"/api/projects/{pid}/sources",
        json={"role": "ASSESSMENT", "raw_text": raw},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "SUMMARIZED"
    assert body["summary_text"] == raw
    assert body["summarized_at"]

    project = (await auth_client.get(f"/api/projects/{pid}")).json()
    assert project["assessment_summary"] == raw


async def test_summarize_endpoint_passthrough(auth_client, monkeypatch):
    monkeypatch.setattr(summarizer_module, "has_openai_key", lambda: False)
    create = await auth_client.post("/api/projects", json={"title": "ReSum"})
    pid = create.json()["id"]
    created = await auth_client.post(
        f"/api/projects/{pid}/sources",
        json={"role": "BACKGROUND", "raw_text": "Background notes here."},
    )
    sid = created.json()["id"]
    again = await auth_client.post(f"/api/projects/{pid}/sources/{sid}/summarize")
    assert again.status_code == 200
    assert again.json()["status"] == "SUMMARIZED"
    assert again.json()["summary_text"] == "Background notes here."


async def test_summarize_endpoint_uses_llm_when_mocked(auth_client, monkeypatch):
    monkeypatch.setattr(summarizer_module, "has_openai_key", lambda: True)
    monkeypatch.setattr(
        summarizer_module.summarizer_service,
        "summarize_text",
        lambda role, raw: ("LLM摘要结果", "llm"),
    )
    create = await auth_client.post("/api/projects", json={"title": "LLMSum"})
    pid = create.json()["id"]
    # 创建时也会走 summarize；再强制调用 endpoint
    created = await auth_client.post(
        f"/api/projects/{pid}/sources",
        json={"role": "ASSESSMENT", "raw_text": "原始评估长文"},
    )
    sid = created.json()["id"]
    assert created.json()["summary_text"] == "LLM摘要结果"

    res = await auth_client.post(f"/api/projects/{pid}/sources/{sid}/summarize")
    assert res.status_code == 200
    assert res.json()["summary_text"] == "LLM摘要结果"

    project = (await auth_client.get(f"/api/projects/{pid}")).json()
    assert project["assessment_summary"] == "LLM摘要结果"
