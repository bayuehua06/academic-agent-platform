"""文献检索 API 测试（mock IEEE/ACM，不启浏览器）。"""

from unittest.mock import AsyncMock, patch

from tests.helpers import (
    _mock_zotero_service,
    prepare_confirmed_literatures,
    prepare_writing_inputs,
)


async def test_list_literature_providers(auth_client):
    res = await auth_client.get("/api/literature-providers")
    assert res.status_code == 200
    providers = res.json()["providers"]
    ids = {p["id"] for p in providers}
    assert "ieee" in ids
    assert "acm" in ids
    ieee = next(p for p in providers if p["id"] == "ieee")
    acm = next(p for p in providers if p["id"] == "acm")
    assert ieee["implemented"] is True
    assert acm["implemented"] is True
    assert "ieee-xplore" in ieee["entry_url"]
    assert "acm" in acm["entry_url"]


async def test_create_project_default_databases(auth_client):
    create = await auth_client.post("/api/projects", json={"title": "DB Default"})
    assert create.status_code == 201
    assert create.json()["literature_databases"] == ["ieee"]


async def test_update_project_databases(auth_client):
    create = await auth_client.post("/api/projects", json={"title": "DB Update"})
    pid = create.json()["id"]
    patch = await auth_client.patch(
        f"/api/projects/{pid}",
        json={"literature_databases": ["ieee", "acm"]},
    )
    assert patch.status_code == 200
    assert patch.json()["literature_databases"] == ["ieee", "acm"]

    bad = await auth_client.patch(
        f"/api/projects/{pid}",
        json={"literature_databases": ["not-a-db"]},
    )
    assert bad.status_code == 400


async def test_literature_search_ping_mocked(auth_client):
    create = await auth_client.post("/api/projects", json={"title": "Ping"})
    pid = create.json()["id"]
    with (
        patch(
            "app.api.literature_search.ieee_aut_search_service.ping",
            new=AsyncMock(
                return_value={
                    "ok": True,
                    "provider": "ieee",
                    "configured": True,
                    "final_url": "https://ieeexplore.ieee.org/",
                }
            ),
        ),
        patch(
            "app.api.literature_search.acm_aut_search_service.ping",
            new=AsyncMock(
                return_value={
                    "ok": True,
                    "provider": "acm",
                    "configured": True,
                    "final_url": "https://dl.acm.org/",
                }
            ),
        ),
    ):
        res = await auth_client.post(f"/api/projects/{pid}/literature-search/ping")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["results"][0]["provider"] == "ieee"


async def test_literature_search_dual_providers_dedupes(auth_client):
    """双库各取 max_results，按 DOI/标题去重。"""
    create = await auth_client.post(
        "/api/projects",
        json={"title": "Dual DB", "literature_databases": ["ieee", "acm"]},
    )
    pid = create.json()["id"]
    await prepare_writing_inputs(auth_client, pid)

    ieee_batch = [
        {
            "title": "Shared Paper",
            "authors": ["A"],
            "year": "2020",
            "doi": "10.1000/shared",
            "provider": "ieee",
        },
        {
            "title": "IEEE Only",
            "authors": ["B"],
            "year": "2021",
            "doi": "10.1109/only",
            "provider": "ieee",
        },
    ]
    acm_batch = [
        {
            "title": "Shared Paper",
            "authors": ["A"],
            "year": "2020",
            "doi": "10.1000/shared",
            "provider": "acm",
        },
        {
            "title": "ACM Only",
            "authors": ["C"],
            "year": "2022",
            "doi": "10.1145/only",
            "provider": "acm",
        },
    ]
    ieee_mock = AsyncMock(return_value=ieee_batch)
    acm_mock = AsyncMock(return_value=acm_batch)
    with (
        patch(
            "app.api.literature_search.ieee_aut_search_service.search",
            new=ieee_mock,
        ),
        patch(
            "app.api.literature_search.acm_aut_search_service.search",
            new=acm_mock,
        ),
    ):
        res = await auth_client.post(
            f"/api/projects/{pid}/literature-search",
            json={
                "outline_heading": "Introduction",
                "query": "q",
                "max_results": 10,
                "databases": ["ieee", "acm"],
            },
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body["providers"]) == {"ieee", "acm"}
    titles = [c["title"] for c in body["candidates"]]
    assert titles == ["Shared Paper", "IEEE Only", "ACM Only"]
    assert body["deduped_count"] == 1
    assert ieee_mock.await_args.kwargs["max_results"] == 10
    assert acm_mock.await_args.kwargs["max_results"] == 10


async def test_literature_search_returns_candidates(auth_client):
    create = await auth_client.post("/api/projects", json={"title": "Search"})
    pid = create.json()["id"]
    await prepare_writing_inputs(auth_client, pid)

    fake = [
        {
            "title": "Food Delivery Paper",
            "authors": ["A B"],
            "year": "2021",
            "doi": "10.1109/TEST.2021.1",
            "abstract": "About food delivery",
            "url": "https://ieeexplore.ieee.org/document/1",
            "provider": "ieee",
        }
    ]
    with patch(
        "app.api.literature_search.ieee_aut_search_service.search",
        new=AsyncMock(return_value=fake),
    ):
        res = await auth_client.post(
            f"/api/projects/{pid}/literature-search",
            json={
                "outline_heading": "Introduction",
                "query": "food delivery transformation",
                "max_results": 5,
            },
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "completed"
    assert body["query"] == "food delivery transformation"
    assert len(body["candidates"]) == 1
    assert body["candidates"][0]["title"] == "Food Delivery Paper"
    assert body["candidates"][0]["outline_heading"] == "Introduction"

    got = await auth_client.get(
        f"/api/projects/{pid}/literature-search/{body['id']}"
    )
    assert got.status_code == 200
    assert got.json()["id"] == body["id"]


async def test_literature_search_uses_test_query_when_empty(auth_client):
    create = await auth_client.post("/api/projects", json={"title": "Default Q"})
    pid = create.json()["id"]
    await prepare_writing_inputs(auth_client, pid)

    mock_search = AsyncMock(
        return_value=[{"title": "T", "authors": [], "provider": "ieee"}]
    )
    with patch(
        "app.api.literature_search.ieee_aut_search_service.search",
        new=mock_search,
    ):
        res = await auth_client.post(
            f"/api/projects/{pid}/literature-search",
            json={"outline_heading": "Introduction"},
        )
    assert res.status_code == 200
    assert mock_search.await_args.args[0] == "food delivery transformation"


async def test_confirm_selected_candidates(auth_client):
    create = await auth_client.post("/api/projects", json={"title": "Confirm"})
    pid = create.json()["id"]
    await prepare_writing_inputs(auth_client, pid)

    fake = [
        {
            "title": "Keep Me",
            "authors": ["A"],
            "year": "2022",
            "doi": "10.1/keep",
            "abstract": "yes",
            "provider": "ieee",
        },
        {
            "title": "Skip Me",
            "authors": ["B"],
            "year": "2021",
            "doi": "10.1/skip",
            "provider": "ieee",
        },
        {
            "title": "Also Keep",
            "authors": ["C"],
            "year": "2020",
            "doi": "10.1/also",
            "provider": "ieee",
        },
    ]
    with patch(
        "app.api.literature_search.ieee_aut_search_service.search",
        new=AsyncMock(return_value=fake),
    ):
        search = await auth_client.post(
            f"/api/projects/{pid}/literature-search",
            json={"outline_heading": "Introduction", "query": "q"},
        )
    assert search.status_code == 200
    run_id = search.json()["id"]

    mock_svc = _mock_zotero_service()
    with (
        patch("app.services.literature_workflow.zotero_service", mock_svc),
        patch("app.api.zotero.zotero_service", mock_svc),
    ):
        conf = await auth_client.post(
            f"/api/projects/{pid}/literature-search/{run_id}/confirm",
            json={"indices": [0, 2]},
        )
    assert conf.status_code == 200, conf.text
    body = conf.json()
    assert len(body) == 2
    titles = {row["title"] for row in body}
    assert titles == {"Keep Me", "Also Keep"}
    assert all(row.get("confirmed_at") for row in body)
    assert all(row.get("outline_heading") == "Introduction" for row in body)

    listed = await auth_client.get(f"/api/zotero/projects/{pid}/literatures")
    assert len(listed.json()) == 2


async def test_literature_search_marks_already_exists(auth_client):
    create = await auth_client.post("/api/projects", json={"title": "Dup Mark"})
    pid = create.json()["id"]
    await prepare_writing_inputs(auth_client, pid)
    _lits, mock_svc = await prepare_confirmed_literatures(auth_client, pid, count=1)

    fake = [
        {
            "title": "Confirmed Paper 1",
            "authors": ["Author 1"],
            "year": "2020",
            "doi": "10.1000/test.1",
            "abstract": "same as imported",
            "provider": "ieee",
        },
        {
            "title": "Brand New Paper",
            "authors": ["X"],
            "year": "2024",
            "doi": "10.1000/new.1",
            "provider": "ieee",
        },
    ]
    with (
        patch(
            "app.api.literature_search.ieee_aut_search_service.search",
            new=AsyncMock(return_value=fake),
        ),
        patch("app.api.literature_search.zotero_service", mock_svc),
    ):
        res = await auth_client.post(
            f"/api/projects/{pid}/literature-search",
            json={"outline_heading": "Literature Review", "query": "q"},
        )
    assert res.status_code == 200, res.text
    cands = res.json()["candidates"]
    assert cands[0]["already_exists"] is True
    assert cands[0]["existing_outline_heading"] == "Introduction"
    assert cands[1]["already_exists"] is False


async def test_confirm_rejects_bad_index(auth_client):
    create = await auth_client.post("/api/projects", json={"title": "Bad Idx"})
    pid = create.json()["id"]
    await prepare_writing_inputs(auth_client, pid)
    with patch(
        "app.api.literature_search.ieee_aut_search_service.search",
        new=AsyncMock(return_value=[{"title": "Only", "provider": "ieee"}]),
    ):
        search = await auth_client.post(
            f"/api/projects/{pid}/literature-search",
            json={"outline_heading": "Introduction", "query": "q"},
        )
    run_id = search.json()["id"]
    bad = await auth_client.post(
        f"/api/projects/{pid}/literature-search/{run_id}/confirm",
        json={"indices": [5]},
    )
    assert bad.status_code == 400
