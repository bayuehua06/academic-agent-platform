"""章节文献分配 API / Attach 分流测试。"""

from unittest.mock import patch

from tests.helpers import (
    _mock_zotero_service,
    prepare_confirmed_literatures,
    prepare_writing_inputs,
)


async def _attach_project_with_lits(auth_client, count: int = 2):
    create = await auth_client.post("/api/projects", json={"title": "Assign Proj"})
    pid = create.json()["id"]
    await prepare_writing_inputs(auth_client, pid)
    mock_svc = _mock_zotero_service(
        seed_items=[
            {
                "zotero_item_key": f"SEED{i}",
                "title": f"Seed Paper {i}",
                "authors": [f"Author {i}"],
                "year": str(2020 + i),
                "doi": f"10.1000/seed.{i}",
                "abstract": "x",
                "zotero_subcollection_key": "EXISTING",
                "outline_heading": None,
            }
            for i in range(1, count + 1)
        ]
    )
    with (
        patch("app.services.literature_workflow.zotero_for_project", return_value=mock_svc),
        patch("app.api.zotero.zotero_service", mock_svc),
        patch("app.services.literature_assignments.zotero_for_project", return_value=mock_svc),
    ):
        bind = await auth_client.post(
            f"/api/zotero/projects/{pid}/binding",
            json={
                "mode": "attach",
                "collection_key": "EXISTING",
                "library_type": "user",
                "library_id": "123",
            },
        )
        assert bind.status_code == 200, bind.text
        lits = (
            await auth_client.get(f"/api/zotero/projects/{pid}/literatures")
        ).json()
    return pid, lits, mock_svc


async def test_put_and_get_assignments(auth_client):
    pid, lits, _mock = await _attach_project_with_lits(auth_client, count=2)
    id0, id1 = lits[0]["id"], lits[1]["id"]

    put = await auth_client.put(
        f"/api/projects/{pid}/literature-assignments/Introduction",
        json={"literature_ids": [id0, id1]},
    )
    assert put.status_code == 200, put.text
    body = put.json()
    intro = next(s for s in body["sections"] if s["outline_heading"] == "Introduction")
    assert set(intro["literature_ids"]) == {id0, id1}
    assert body["unassigned_count"] == 0

    # 同一篇再分给另一章
    put2 = await auth_client.put(
        f"/api/projects/{pid}/literature-assignments/Literature%20Review",
        json={"literature_ids": [id0]},
    )
    assert put2.status_code == 200, put2.text
    listed = (await auth_client.get(f"/api/zotero/projects/{pid}/literatures")).json()
    by_id = {row["id"]: row for row in listed}
    assert "Introduction" in by_id[id0]["assigned_headings"]
    assert "Literature Review" in by_id[id0]["assigned_headings"]
    assert by_id[id1]["assigned_headings"] == ["Introduction"]


async def test_attach_blocks_literature_search(auth_client):
    pid, _lits, _mock = await _attach_project_with_lits(auth_client, count=1)
    res = await auth_client.post(
        f"/api/projects/{pid}/literature-search",
        json={"outline_heading": "Introduction", "query": "test"},
    )
    assert res.status_code == 400
    assert "章节分配" in res.json()["detail"]


async def test_attach_blocks_import(auth_client):
    pid, _lits, mock_svc = await _attach_project_with_lits(auth_client, count=1)
    with (
        patch("app.services.literature_workflow.zotero_for_project", return_value=mock_svc),
        patch("app.api.zotero.zotero_service", mock_svc),
    ):
        res = await auth_client.post(
            f"/api/zotero/projects/{pid}/import",
            json={
                "outline_heading": "Introduction",
                "target_collection_key": "EXISTING",
                "items": [{"title": "Nope", "doi": "10.1000/nope"}],
            },
        )
    assert res.status_code == 400


async def test_attach_writer_sources_only_assigned(auth_client):
    """run-agent 在 attach 下只把已分配文献送入 Writer。"""
    from unittest.mock import MagicMock

    pid, lits, mock_svc = await _attach_project_with_lits(auth_client, count=2)
    id0 = lits[0]["id"]
    await auth_client.put(
        f"/api/projects/{pid}/literature-assignments/Introduction",
        json={"literature_ids": [id0]},
    )

    captured = {}

    def _fake_run(**kwargs):
        captured["sources"] = kwargs.get("existing_sources") or []
        return {
            "draft_markdown": "# Draft\n\n## Introduction\n\nHello.\n",
            "apa_references": "",
        }

    with (
        patch("app.services.literature_workflow.zotero_for_project", return_value=mock_svc),
        patch("app.api.projects.run_academic_workflow", side_effect=_fake_run),
    ):
        res = await auth_client.post(
            f"/api/projects/{pid}/run-agent",
            json={"skip_search": True, "max_papers": 5},
        )
    assert res.status_code == 200, res.text
    assert len(captured["sources"]) == 1
    assert captured["sources"][0]["title"] == "Seed Paper 1"
    assert captured["sources"][0]["assigned_headings"] == ["Introduction"]


async def test_create_mode_still_imports(auth_client):
    create = await auth_client.post("/api/projects", json={"title": "Create Still"})
    pid = create.json()["id"]
    await prepare_writing_inputs(auth_client, pid)
    lits, _mock = await prepare_confirmed_literatures(auth_client, pid, count=1)
    assert lits[0]["outline_heading"] == "Introduction"


async def test_sync_preserves_section_assignments(auth_client):
    """同集合重新同步：新增远端文献，已有条目的章节分配保留。"""
    pid, lits, mock_svc = await _attach_project_with_lits(auth_client, count=2)
    id0 = lits[0]["id"]
    put = await auth_client.put(
        f"/api/projects/{pid}/literature-assignments/Introduction",
        json={"literature_ids": [id0]},
    )
    assert put.status_code == 200, put.text

    mock_svc._store.append(
        {
            "zotero_item_key": "SEED_NEW",
            "title": "Newly Added Offline",
            "authors": ["N"],
            "year": "2025",
            "doi": "10.1000/seed.new",
            "abstract": "new",
            "zotero_subcollection_key": "EXISTING",
            "outline_heading": None,
        }
    )
    with (
        patch("app.services.literature_workflow.zotero_for_project", return_value=mock_svc),
        patch("app.api.zotero.zotero_service", mock_svc),
        patch("app.services.literature_assignments.zotero_for_project", return_value=mock_svc),
    ):
        sync = await auth_client.post(f"/api/zotero/projects/{pid}/sync")
    assert sync.status_code == 200, sync.text
    assert len(sync.json()) == 3

    listed = (await auth_client.get(f"/api/zotero/projects/{pid}/literatures")).json()
    by_title = {row["title"]: row for row in listed}
    assert by_title["Seed Paper 1"]["assigned_headings"] == ["Introduction"]
    assert by_title["Seed Paper 2"]["assigned_headings"] == []
    assert by_title["Newly Added Offline"]["assigned_headings"] == []


async def test_rebind_same_collection_keeps_assignments(auth_client):
    pid, lits, mock_svc = await _attach_project_with_lits(auth_client, count=1)
    id0 = lits[0]["id"]
    await auth_client.put(
        f"/api/projects/{pid}/literature-assignments/Introduction",
        json={"literature_ids": [id0]},
    )
    with (
        patch("app.services.literature_workflow.zotero_for_project", return_value=mock_svc),
        patch("app.api.zotero.zotero_service", mock_svc),
        patch("app.services.literature_assignments.zotero_for_project", return_value=mock_svc),
    ):
        again = await auth_client.post(
            f"/api/zotero/projects/{pid}/binding",
            json={
                "mode": "attach",
                "collection_key": "EXISTING",
                "library_type": "user",
                "library_id": "123",
            },
        )
    assert again.status_code == 200, again.text
    assert again.json().get("assignments_cleared") is False
    listed = (await auth_client.get(f"/api/zotero/projects/{pid}/literatures")).json()
    assert listed[0]["assigned_headings"] == ["Introduction"]


async def test_rebind_different_collection_clears_assignments(auth_client):
    pid, lits, mock_svc = await _attach_project_with_lits(auth_client, count=1)
    id0 = lits[0]["id"]
    await auth_client.put(
        f"/api/projects/{pid}/literature-assignments/Introduction",
        json={"literature_ids": [id0]},
    )
    mock_svc._store.clear()
    mock_svc._store.append(
        {
            "zotero_item_key": "OTHER1",
            "title": "Other Coll Paper",
            "authors": ["O"],
            "year": "2022",
            "doi": "10.1000/other.1",
            "abstract": "o",
            "zotero_subcollection_key": "OTHER",
            "outline_heading": None,
        }
    )
    with (
        patch("app.services.literature_workflow.zotero_for_project", return_value=mock_svc),
        patch("app.api.zotero.zotero_service", mock_svc),
        patch("app.services.literature_assignments.zotero_for_project", return_value=mock_svc),
    ):
        switched = await auth_client.post(
            f"/api/zotero/projects/{pid}/binding",
            json={
                "mode": "attach",
                "collection_key": "OTHER",
                "library_type": "user",
                "library_id": "123",
            },
        )
    assert switched.status_code == 200, switched.text
    assert switched.json().get("assignments_cleared") is True
    listed = (await auth_client.get(f"/api/zotero/projects/{pid}/literatures")).json()
    assert len(listed) == 1
    assert listed[0]["title"] == "Other Coll Paper"
    assert listed[0]["assigned_headings"] == []


async def test_filter_sources_for_heading_unit():
    from app.services.literature_assignments import filter_sources_for_heading

    sources = [
        {"title": "A", "assigned_headings": ["Introduction"]},
        {"title": "B", "assigned_headings": ["Methods", "Introduction"]},
        {"title": "C", "assigned_headings": ["Methods"]},
    ]
    intro = filter_sources_for_heading(sources, "Introduction")
    assert {s["title"] for s in intro} == {"A", "B"}
    plain = [{"title": "X"}, {"title": "Y"}]
    assert filter_sources_for_heading(plain, "Introduction") == plain
