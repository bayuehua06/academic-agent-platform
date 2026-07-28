"""项目 CRUD 与 Agent 触发 API 测试。"""

from unittest.mock import patch

from tests.helpers import prepare_confirmed_literatures, prepare_writing_inputs


async def test_agent_progress_idle_and_set(auth_client):
    from app.services.agent_progress import clear_agent_progress, set_agent_progress

    create = await auth_client.post("/api/projects", json={"title": "Progress"})
    pid = create.json()["id"]

    idle = await auth_client.get(f"/api/projects/{pid}/agent-progress")
    assert idle.status_code == 200
    assert idle.json()["running"] is False
    assert idle.json()["stage"] == "idle"

    set_agent_progress(pid, "evidence", detail="building cards", percent=40)
    try:
        got = await auth_client.get(f"/api/projects/{pid}/agent-progress")
        assert got.status_code == 200
        body = got.json()
        assert body["running"] is True
        assert body["stage"] == "evidence"
        assert "证据" in body["label"]
        assert body["percent"] == 40
        assert "building" in body["detail"]
    finally:
        clear_agent_progress(pid)


async def test_list_projects_empty(auth_client):
    res = await auth_client.get("/api/projects")
    assert res.status_code == 200
    assert res.json() == []


async def test_create_and_get_project(auth_client):
    create = await auth_client.post(
        "/api/projects",
        json={"title": "APA Review"},
    )
    assert create.status_code == 201
    project = create.json()
    assert project["title"] == "APA Review"
    assert project["status"] == "INITIALIZING"
    assert project["literature_count"] == 0
    assert project["source_document_count"] == 0
    assert project["assessment_summary"] is None
    assert project["assessment_ready"] is False
    assert project["outline_ready"] is False

    got = await auth_client.get(f"/api/projects/{project['id']}")
    assert got.status_code == 200
    assert got.json()["id"] == project["id"]


async def test_update_project(auth_client):
    create = await auth_client.post("/api/projects", json={"title": "Draft"})
    pid = create.json()["id"]

    patch = await auth_client.patch(
        f"/api/projects/{pid}",
        json={
            "title": "Updated",
            "assessment_summary": "Focus on ethics",
            "specific_requirements": "Use APA 7th",
        },
    )
    assert patch.status_code == 200
    body = patch.json()
    assert body["title"] == "Updated"
    assert body["assessment_summary"] == "Focus on ethics"
    assert body["specific_requirements"] == "Use APA 7th"
    assert body["assessment_ready"] is True


async def test_delete_project(auth_client):
    create = await auth_client.post("/api/projects", json={"title": "Temp"})
    pid = create.json()["id"]

    deleted = await auth_client.delete(f"/api/projects/{pid}")
    assert deleted.status_code == 204

    missing = await auth_client.get(f"/api/projects/{pid}")
    assert missing.status_code == 404


async def test_project_requires_auth(client):
    res = await client.get("/api/projects")
    assert res.status_code == 401


async def test_old_notebook_routes_gone(auth_client):
    create = await auth_client.post("/api/projects", json={"title": "No Notebook"})
    pid = create.json()["id"]
    res = await auth_client.get(f"/api/notebook/{pid}")
    assert res.status_code == 404


async def test_project_status_derives_from_progress(auth_client):
    create = await auth_client.post("/api/projects", json={"title": "Phases"})
    pid = create.json()["id"]
    assert create.json()["status"] == "INITIALIZING"

    await auth_client.post(
        f"/api/projects/{pid}/sources",
        json={"role": "ASSESSMENT", "raw_text": "Write an APA review on tutoring."},
    )
    mid = (await auth_client.get(f"/api/projects/{pid}")).json()
    assert mid["status"] == "INPUTS_IN_PROGRESS"
    assert mid["assessment_ready"] is True

    await prepare_writing_inputs(auth_client, pid)
    locked = (await auth_client.get(f"/api/projects/{pid}")).json()
    assert locked["status"] == "OUTLINE_LOCKED"
    assert locked["outline_ready"] is True


async def test_run_agent_requires_assessment_and_locked_outline(auth_client):
    create = await auth_client.post("/api/projects", json={"title": "Not Ready"})
    pid = create.json()["id"]
    run = await auth_client.post(
        f"/api/projects/{pid}/run-agent",
        json={"max_papers": 3, "skip_search": False},
    )
    assert run.status_code == 400
    assert "Assessment" in run.json()["detail"] or "大纲" in run.json()["detail"]


async def test_run_agent_allows_zero_literature(auth_client, monkeypatch):
    """允许零文献写作：仅需 A 定稿 + 锁定 C。"""
    from app.services import summarizer as summarizer_module

    monkeypatch.setattr(summarizer_module, "has_openai_key", lambda: False)
    create = await auth_client.post("/api/projects", json={"title": "No Lit OK"})
    pid = create.json()["id"]
    await prepare_writing_inputs(auth_client, pid)
    run = await auth_client.post(
        f"/api/projects/{pid}/run-agent",
        json={"max_papers": 3},
    )
    assert run.status_code == 200, run.text
    draft = run.json()
    assert draft["source_type"] == "AGENT_GEN"
    assert draft["content_markdown"]
    project = (await auth_client.get(f"/api/projects/{pid}")).json()
    assert project["status"] == "HAS_DRAFT"
    assert project["literature_count"] == 0


async def test_run_agent_creates_draft_and_literatures(auth_client, monkeypatch):
    from app.services import summarizer as summarizer_module

    # 避免本机 .env 有 Key 时真实调用 OpenAI
    monkeypatch.setattr(summarizer_module, "has_openai_key", lambda: False)
    create = await auth_client.post("/api/projects", json={"title": "Agent Run"})
    pid = create.json()["id"]
    await prepare_writing_inputs(auth_client, pid)
    _lits, mock_svc = await prepare_confirmed_literatures(auth_client, pid, count=3)

    with patch("app.services.literature_workflow.zotero_for_project", return_value=mock_svc):
        run = await auth_client.post(
            f"/api/projects/{pid}/run-agent",
            json={"max_papers": 3, "skip_search": True, "auto_repair": False},
        )
    assert run.status_code == 200
    draft = run.json()
    assert draft["version_number"] == 1
    assert draft["source_type"] == "AGENT_GEN"
    assert draft["content_markdown"]
    assert draft["apa_references_block"]
    assert "writer=template" in (draft.get("changelog") or "")
    assert "verify_ok" in draft
    # 默认不自动 repair：校验失败时应可询问
    if draft.get("verify_ok") is False:
        assert draft.get("repair_available") is True
        assert "repair_skipped=True" in (draft.get("changelog") or "")

    project = (await auth_client.get(f"/api/projects/{pid}")).json()
    assert project["status"] == "HAS_DRAFT"

    assert project["literature_count"] == 3
    assert project["latest_version"] == 1
    assert project["assessment_ready"] is True
    assert project["outline_ready"] is True

    lits = (
        await auth_client.get(f"/api/zotero/projects/{pid}/literatures")
    ).json()
    assert len(lits) == 3
    assert all(item["title"] for item in lits)
    assert all(item.get("confirmed_at") for item in lits)


async def test_repair_agent_draft_creates_new_version(auth_client, monkeypatch):
    from app.services import summarizer as summarizer_module
    from app.services.writing_constraints import WritingConstraints

    monkeypatch.setattr(summarizer_module, "has_openai_key", lambda: False)
    create = await auth_client.post("/api/projects", json={"title": "Repair Flow"})
    pid = create.json()["id"]
    await prepare_writing_inputs(auth_client, pid)
    run = await auth_client.post(
        f"/api/projects/{pid}/run-agent",
        json={"max_papers": 3, "skip_search": True, "auto_repair": False},
    )
    assert run.status_code == 200
    base = run.json()

    def fake_repair(md, **kwargs):  # noqa: ANN001
        fixed = (md or "") + "\n\nCritical reflection added for repair test.\n"
        v = {
            "ok": True,
            "issues": [],
            "word_count": 120,
            "word_target": {"min": 100, "max": 200},
            "repaired": True,
        }
        return fixed, WritingConstraints(), v

    with patch("app.api.projects.repair_draft_markdown", side_effect=fake_repair):
        repaired = await auth_client.post(
            f"/api/projects/{pid}/repair-agent-draft",
            json={"version_id": base["id"]},
        )
    assert repaired.status_code == 200, repaired.text
    body = repaired.json()
    assert body["source_type"] == "AGENT_REPAIR"
    assert body["repaired"] is True
    assert body["version_number"] == base["version_number"] + 1
    assert "Critical reflection" in body["content_markdown"]
    assert body.get("repair_available") is False
