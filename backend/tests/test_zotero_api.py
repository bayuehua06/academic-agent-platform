"""文献 / Zotero API 测试。"""

from unittest.mock import patch

from tests.helpers import (
    _mock_zotero_service,
    prepare_confirmed_literatures,
    prepare_writing_inputs,
)


async def _project_with_literature(auth_client) -> tuple[str, str]:
    """准备确认文献，返回 (project_id, literature_id)。"""
    create = await auth_client.post(
        "/api/projects",
        json={"title": "Lit"},
    )
    pid = create.json()["id"]
    await prepare_writing_inputs(auth_client, pid)
    lits, _mock = await prepare_confirmed_literatures(auth_client, pid, count=2)
    return pid, lits[0]["id"]



async def test_zotero_status(auth_client):
    res = await auth_client.get("/api/zotero/status")
    assert res.status_code == 200
    body = res.json()
    assert "configured" in body
    assert body["configured"] is False


async def test_zotero_ping_unconfigured(auth_client):
    res = await auth_client.get("/api/zotero/ping")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert body["configured"] is False


async def test_zotero_ping_ok(auth_client):
    mock_svc = _mock_zotero_service()
    with patch("app.api.zotero.zotero_service", mock_svc):
        res = await auth_client.get("/api/zotero/ping")
    assert res.status_code == 200
    assert res.json()["ok"] is True


async def test_ensure_structure(auth_client):
    create = await auth_client.post("/api/projects", json={"title": "Struct Proj"})
    pid = create.json()["id"]
    await prepare_writing_inputs(auth_client, pid)

    mock_svc = _mock_zotero_service()
    with (
        patch("app.services.literature_workflow.zotero_service", mock_svc),
        patch("app.api.zotero.zotero_service", mock_svc),
    ):
        res = await auth_client.post(f"/api/zotero/projects/{pid}/ensure-structure")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["zotero_collection_id"] == "ROOTKEY"
    assert len(body["subcollections"]) == 3

    project = (await auth_client.get(f"/api/projects/{pid}")).json()
    assert project["zotero_collection_id"] == "ROOTKEY"


async def test_import_literatures(auth_client):
    create = await auth_client.post("/api/projects", json={"title": "Import Proj"})
    pid = create.json()["id"]
    await prepare_writing_inputs(auth_client, pid)
    lits, _mock = await prepare_confirmed_literatures(auth_client, pid, count=2)
    assert lits[0]["outline_heading"] == "Introduction"
    assert lits[0]["zotero_subcollection_key"] == "SUBINTRO"
    assert lits[0]["zotero_item_key"]


async def test_sync_from_zotero_pulls_remote(auth_client):
    create = await auth_client.post("/api/projects", json={"title": "Sync Proj"})
    pid = create.json()["id"]
    await prepare_writing_inputs(auth_client, pid)
    _lits, mock_svc = await prepare_confirmed_literatures(auth_client, pid, count=1)
    # 模拟离线在 Zotero 新增一篇
    mock_svc._store.append(
        {
            "zotero_item_key": "OFFLINE1",
            "title": "Offline Added Paper",
            "authors": ["Offline A"],
            "year": "2024",
            "doi": "10.1000/offline.1",
            "abstract": "added in desktop",
            "zotero_subcollection_key": "SUBINTRO",
            "outline_heading": "Introduction",
        }
    )
    with patch("app.services.literature_workflow.zotero_service", mock_svc):
        res = await auth_client.post(f"/api/zotero/projects/{pid}/sync")
    assert res.status_code == 200, res.text
    titles = {row["title"] for row in res.json()}
    assert "Offline Added Paper" in titles
    assert "Confirmed Paper 1" in titles


async def test_list_literatures(auth_client):
    pid, _ = await _project_with_literature(auth_client)
    res = await auth_client.get(f"/api/zotero/projects/{pid}/literatures")
    assert res.status_code == 200
    assert len(res.json()) == 2


async def test_update_literature_selected(auth_client):
    _, lit_id = await _project_with_literature(auth_client)
    res = await auth_client.patch(
        f"/api/zotero/literatures/{lit_id}",
        json={"selected_for_draft": False, "relevance_score": 0.5},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["selected_for_draft"] is False
    assert body["relevance_score"] == 0.5
