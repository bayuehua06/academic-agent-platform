"""草稿版本、导出与 Word 导入 API 测试。"""

from io import BytesIO
from unittest.mock import patch

from docx import Document

from tests.helpers import prepare_confirmed_literatures, prepare_writing_inputs


async def _project_with_draft(auth_client) -> tuple[str, dict]:
    create = await auth_client.post(
        "/api/projects",
        json={"title": "Drafts"},
    )
    pid = create.json()["id"]
    await prepare_writing_inputs(auth_client, pid)
    _lits, mock_svc = await prepare_confirmed_literatures(auth_client, pid, count=2)
    with patch("app.services.literature_workflow.zotero_service", mock_svc):
        run = await auth_client.post(
            f"/api/projects/{pid}/run-agent",
            json={"max_papers": 2, "skip_search": True},
        )
    assert run.status_code == 200
    return pid, run.json()


def _make_docx_bytes(paragraphs: list[str]) -> bytes:
    buf = BytesIO()
    doc = Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    doc.save(buf)
    return buf.getvalue()


async def test_list_and_latest_draft(auth_client):
    pid, draft = await _project_with_draft(auth_client)
    listed = await auth_client.get(f"/api/drafts/{pid}")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["id"] == draft["id"]

    latest = await auth_client.get(f"/api/drafts/{pid}/latest")
    assert latest.status_code == 200
    assert latest.json()["version_number"] == 1


async def test_latest_draft_404_when_empty(auth_client):
    create = await auth_client.post("/api/projects", json={"title": "Empty"})
    pid = create.json()["id"]
    res = await auth_client.get(f"/api/drafts/{pid}/latest")
    assert res.status_code == 404


async def test_export_docx(auth_client):
    pid, _ = await _project_with_draft(auth_client)
    res = await auth_client.get(f"/api/drafts/{pid}/export?format=docx")
    assert res.status_code == 200
    assert (
        "wordprocessingml" in res.headers.get("content-type", "")
        or res.headers.get("content-type", "").startswith("application/")
    )
    assert len(res.content) > 100


async def test_import_docx_creates_manual_version(auth_client):
    pid, first = await _project_with_draft(auth_client)
    payload = _make_docx_bytes(
        ["# Imported Draft", "This paragraph was edited in Word."]
    )
    res = await auth_client.post(
        f"/api/drafts/import-docx?project_id={pid}",
        files={
            "file": (
                "edited.docx",
                payload,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["version_number"] == first["version_number"] + 1
    assert body["source_type"] == "MANUAL_IMPORT"
    assert (
        "Imported" in body["content_markdown"]
        or "edited" in body["content_markdown"].lower()
        or "Word" in body["content_markdown"]
    )


async def test_import_rejects_non_docx(auth_client):
    create = await auth_client.post("/api/projects", json={"title": "Bad"})
    pid = create.json()["id"]
    res = await auth_client.post(
        f"/api/drafts/import-docx?project_id={pid}",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert res.status_code == 400
