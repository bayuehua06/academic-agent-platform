"""草稿工作区 P0：上传 → working → 确认 minor。"""

from io import BytesIO
from unittest.mock import patch

from docx import Document

from app.services import summarizer as summarizer_module
from tests.helpers import prepare_confirmed_literatures, prepare_writing_inputs


def _make_docx_bytes(paragraphs: list[str]) -> bytes:
    buf = BytesIO()
    doc = Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    doc.save(buf)
    return buf.getvalue()


async def _project_with_agent_draft(auth_client) -> tuple[str, dict]:
    create = await auth_client.post("/api/projects", json={"title": "Polish P0"})
    pid = create.json()["id"]
    await prepare_writing_inputs(auth_client, pid)
    _lits, mock_svc = await prepare_confirmed_literatures(auth_client, pid, count=1)
    with (
        patch.object(summarizer_module, "has_openai_key", lambda: False),
        patch("app.services.literature_workflow.zotero_service", mock_svc),
    ):
        run = await auth_client.post(
            f"/api/projects/{pid}/run-agent",
            json={"max_papers": 1, "skip_search": True},
        )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["display_label"] == "1"
    assert body["major"] == 1
    assert body["minor"] == 0
    return pid, body


async def test_import_opens_working_then_confirm_minor(auth_client):
    pid, base = await _project_with_agent_draft(auth_client)
    payload = _make_docx_bytes(["# Intro", "Edited by hand in Word."])

    # 缺 base → 422
    bad = await auth_client.post(
        f"/api/drafts/import-docx?project_id={pid}",
        files={
            "file": (
                "edited.docx",
                payload,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert bad.status_code == 422

    imp = await auth_client.post(
        f"/api/drafts/import-docx?project_id={pid}&base_version_id={base['id']}",
        files={
            "file": (
                "edited.docx",
                payload,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert imp.status_code == 201, imp.text
    working = imp.json()
    assert working["status"] == "ACTIVE"
    assert working["base_version_id"] == base["id"]
    assert "Edited" in working["content_markdown"] or "hand" in working["content_markdown"].lower()

    got = await auth_client.get(f"/api/drafts/{pid}/working")
    assert got.status_code == 200
    assert got.json()["id"] == working["id"]

    # 确认前版本列表仍只有 v1
    listed = await auth_client.get(f"/api/drafts/{pid}")
    assert len(listed.json()) == 1
    assert listed.json()[0]["display_label"] == "1"

    conf = await auth_client.post(f"/api/drafts/{pid}/working/confirm")
    assert conf.status_code == 200, conf.text
    v11 = conf.json()
    assert v11["display_label"] == "1.1"
    assert v11["major"] == 1
    assert v11["minor"] == 1
    assert v11["source_type"] == "POLISH_CONFIRM"
    assert v11["base_version_id"] == base["id"]

    # 工作区已清空
    empty = await auth_client.get(f"/api/drafts/{pid}/working")
    assert empty.status_code == 200
    assert empty.json() is None

    listed2 = await auth_client.get(f"/api/drafts/{pid}")
    labels = [d["display_label"] for d in listed2.json()]
    assert labels[0] == "1.1"
    assert "1" in labels


async def test_discard_working(auth_client):
    pid, base = await _project_with_agent_draft(auth_client)
    payload = _make_docx_bytes(["Discard me"])
    imp = await auth_client.post(
        f"/api/drafts/import-docx?project_id={pid}&base_version_id={base['id']}",
        files={
            "file": (
                "x.docx",
                payload,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert imp.status_code == 201
    disc = await auth_client.delete(f"/api/drafts/{pid}/working")
    assert disc.status_code == 204
    got = await auth_client.get(f"/api/drafts/{pid}/working")
    assert got.json() is None


async def test_second_confirm_is_1_2(auth_client):
    pid, base = await _project_with_agent_draft(auth_client)
    payload = _make_docx_bytes(["Round one"])
    await auth_client.post(
        f"/api/drafts/import-docx?project_id={pid}&base_version_id={base['id']}",
        files={
            "file": (
                "a.docx",
                payload,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    c1 = await auth_client.post(f"/api/drafts/{pid}/working/confirm")
    assert c1.json()["display_label"] == "1.1"

    payload2 = _make_docx_bytes(["Round two"])
    await auth_client.post(
        f"/api/drafts/import-docx?project_id={pid}&base_version_id={c1.json()['id']}",
        files={
            "file": (
                "b.docx",
                payload2,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    c2 = await auth_client.post(f"/api/drafts/{pid}/working/confirm")
    assert c2.json()["display_label"] == "1.2"
    assert c2.json()["major"] == 1
    assert c2.json()["minor"] == 2


async def test_start_working_without_upload(auth_client):
    pid, base = await _project_with_agent_draft(auth_client)
    res = await auth_client.post(
        f"/api/drafts/{pid}/working/start?base_version_id={base['id']}"
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "ACTIVE"
    assert body["base_version_id"] == base["id"]
    assert body["source_filename"] is None
    assert len(body.get("sections") or []) >= 1
