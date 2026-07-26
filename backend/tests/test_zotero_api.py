"""文献 / Zotero API 测试。"""

from tests.helpers import prepare_writing_inputs


async def _project_with_literature(auth_client) -> tuple[str, str]:
    """运行 agent 生成文献，返回 (project_id, literature_id)。"""
    create = await auth_client.post(
        "/api/projects",
        json={"title": "Lit"},
    )
    pid = create.json()["id"]
    await prepare_writing_inputs(auth_client, pid)
    run = await auth_client.post(
        f"/api/projects/{pid}/run-agent",
        json={"max_papers": 2, "skip_search": False},
    )
    assert run.status_code == 200
    lits = (
        await auth_client.get(f"/api/zotero/projects/{pid}/literatures")
    ).json()
    assert len(lits) >= 1
    return pid, lits[0]["id"]


async def test_zotero_status(auth_client):
    res = await auth_client.get("/api/zotero/status")
    assert res.status_code == 200
    body = res.json()
    assert "configured" in body
    assert body["configured"] is False


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
