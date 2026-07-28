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
        patch("app.services.literature_workflow.zotero_for_project", return_value=mock_svc),
        patch("app.api.zotero.zotero_service", mock_svc),
    ):
        res = await auth_client.post(f"/api/zotero/projects/{pid}/ensure-structure")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["zotero_collection_id"] == "ROOTKEY"
    assert len(body["subcollections"]) == 3

    project = (await auth_client.get(f"/api/projects/{pid}")).json()
    assert project["zotero_collection_id"] == "ROOTKEY"
    assert project["zotero_binding_mode"] == "create"


async def test_bind_create(auth_client):
    create = await auth_client.post("/api/projects", json={"title": "Bind Create"})
    pid = create.json()["id"]
    await prepare_writing_inputs(auth_client, pid)
    mock_svc = _mock_zotero_service()
    with (
        patch("app.services.literature_workflow.zotero_for_project", return_value=mock_svc),
        patch("app.api.zotero.zotero_service", mock_svc),
    ):
        res = await auth_client.post(
            f"/api/zotero/projects/{pid}/binding",
            json={"mode": "create"},
        )
    assert res.status_code == 200, res.text
    assert res.json()["zotero_binding_mode"] == "create"
    project = (await auth_client.get(f"/api/projects/{pid}")).json()
    assert project["zotero_collection_id"] == "ROOTKEY"
    assert project["zotero_binding_mode"] == "create"


async def test_bind_attach_syncs_and_blocks_ensure(auth_client):
    create = await auth_client.post("/api/projects", json={"title": "Bind Attach"})
    pid = create.json()["id"]
    await prepare_writing_inputs(auth_client, pid)
    mock_svc = _mock_zotero_service(
        seed_items=[
            {
                "zotero_item_key": "OLD1",
                "title": "Preexisting Paper",
                "authors": ["A"],
                "year": "2021",
                "doi": "10.1000/pre.1",
                "abstract": "x",
                "zotero_subcollection_key": "EXISTING",
                "outline_heading": None,
            }
        ]
    )
    with (
        patch("app.services.literature_workflow.zotero_for_project", return_value=mock_svc),
        patch("app.api.zotero.zotero_service", mock_svc),
    ):
        res = await auth_client.post(
            f"/api/zotero/projects/{pid}/binding",
            json={
                "mode": "attach",
                "collection_key": "EXISTING",
                "library_type": "user",
                "library_id": "123",
            },
        )
        assert res.status_code == 200, res.text
        assert res.json()["synced_count"] == 1
        blocked = await auth_client.post(f"/api/zotero/projects/{pid}/ensure-structure")
    assert blocked.status_code == 400
    project = (await auth_client.get(f"/api/projects/{pid}")).json()
    assert project["zotero_binding_mode"] == "attach"
    assert project["zotero_collection_id"] == "EXISTING"
    assert project["zotero_library_id"] == "123"
    lits = (await auth_client.get(f"/api/zotero/projects/{pid}/literatures")).json()
    assert any(row["title"] == "Preexisting Paper" for row in lits)


async def test_attach_blocks_import_entirely(auth_client):
    """Attach 废止平台写回 Zotero：即使带 target 也 400。"""
    create = await auth_client.post("/api/projects", json={"title": "Attach Import"})
    pid = create.json()["id"]
    await prepare_writing_inputs(auth_client, pid)
    mock_svc = _mock_zotero_service()
    with (
        patch("app.services.literature_workflow.zotero_for_project", return_value=mock_svc),
        patch("app.api.zotero.zotero_service", mock_svc),
    ):
        bind = await auth_client.post(
            f"/api/zotero/projects/{pid}/binding",
            json={
                "mode": "attach",
                "collection_key": "EXISTING",
                "library_type": "group",
                "library_id": "999",
            },
        )
        assert bind.status_code == 200, bind.text
        blocked = await auth_client.post(
            f"/api/zotero/projects/{pid}/import",
            json={
                "outline_heading": "Introduction",
                "target_collection_key": "EXISTING",
                "items": [{"title": "New Paper", "doi": "10.1000/n.1"}],
            },
        )
    assert blocked.status_code == 400
    assert "章节分配" in blocked.json()["detail"]


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
    with patch(
        "app.services.literature_workflow.zotero_for_project", return_value=mock_svc
    ):
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
