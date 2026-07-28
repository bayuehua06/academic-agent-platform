"""测试辅助：准备写作所需的 A + 锁定 C，以及已确认文献。"""

from __future__ import annotations

from typing import List, Optional, Tuple
from unittest.mock import MagicMock, patch

_SUB_HEADING = {
    "SUBINTRO": "Introduction",
    "SUBLR": "Literature Review",
    "SUBCONC": "Conclusion",
}


async def prepare_writing_inputs(auth_client, project_id: str) -> None:
    """创建 Assessment + Specific + Outline 并锁定，满足 run-agent 前置。"""
    await auth_client.post(
        f"/api/projects/{project_id}/sources",
        json={
            "role": "ASSESSMENT",
            "raw_text": "Machine learning in education. Requirement: APA.",
        },
    )
    await auth_client.post(
        f"/api/projects/{project_id}/sources",
        json={
            "role": "SPECIFIC",
            "raw_text": "Constraint: focus on higher education.",
        },
    )
    outline = await auth_client.post(
        f"/api/projects/{project_id}/sources",
        json={
            "role": "OUTLINE",
            "raw_text": "# Introduction\n\n# Literature Review\n\n# Conclusion\n",
        },
    )
    assert outline.status_code == 201
    lock = await auth_client.post(
        f"/api/projects/{project_id}/outline/lock",
        json={"source_id": outline.json()["id"]},
    )
    assert lock.status_code == 200


def _mock_zotero_service(seed_items: Optional[List[dict]] = None) -> MagicMock:
    """构造可写入/拉取的假 Zotero 服务。"""
    mock_svc = MagicMock()
    mock_svc.is_configured = True
    mock_svc.ensure_project_structure.return_value = (
        "ROOTKEY",
        {
            "Introduction": "SUBINTRO",
            "Literature Review": "SUBLR",
            "Conclusion": "SUBCONC",
        },
    )
    store: List[dict] = list(seed_items or [])
    counter = {"n": len(store)}

    def _create(meta, collection_id=None):  # noqa: ANN001
        counter["n"] += 1
        key = f"ITEM{counter['n']}"
        store.append(
            {
                "zotero_item_key": key,
                "title": meta.get("title") or "Untitled",
                "authors": meta.get("authors") or [],
                "year": meta.get("year"),
                "doi": meta.get("doi"),
                "abstract": meta.get("abstract"),
                "zotero_subcollection_key": collection_id,
                "outline_heading": _SUB_HEADING.get(collection_id or ""),
            }
        )
        return key

    mock_svc.create_item_from_meta.side_effect = _create
    mock_svc.fetch_project_collection_items.side_effect = (
        lambda root_key, limit_per_collection=200: list(store)
    )
    mock_svc._store = store  # type: ignore[attr-defined]
    mock_svc.ping.return_value = {
        "ok": True,
        "configured": True,
        "library_id": "test",
        "library_type": "user",
        "collection_count": 1,
    }
    mock_svc.list_collections.return_value = [
        {"key": "ROOTKEY", "name": "Test", "parentCollection": False}
    ]
    mock_svc.collection_exists.return_value = True
    mock_svc.list_child_collections.return_value = [
        {"key": "SUBINTRO", "name": "Introduction"},
        {"key": "SUBLR", "name": "Literature Review"},
        {"key": "SUBCONC", "name": "Conclusion"},
    ]
    mock_svc.list_accessible_top_collections.return_value = [
        {
            "key": "EXISTING",
            "name": "Existing Coll",
            "library_type": "user",
            "library_id": "123",
            "library_name": "My Library",
        }
    ]
    return mock_svc


async def prepare_confirmed_literatures(
    auth_client,
    project_id: str,
    count: int = 2,
    outline_heading: str = "Introduction",
) -> Tuple[list, MagicMock]:
    """
    通过 mock Zotero 将确认文献写入项目（含 confirmed_at）。

    Returns:
        (创建的文献 JSON 列表, mock_svc) — mock_svc 可用于后续 sync / run-agent。
    """
    mock_svc = _mock_zotero_service()
    items = [
        {
            "title": f"Confirmed Paper {i + 1}",
            "authors": [f"Author {i + 1}"],
            "year": str(2020 + i),
            "doi": f"10.1000/test.{i + 1}",
            "abstract": f"Abstract {i + 1}",
            "relevance_score": 0.9 - i * 0.1,
        }
        for i in range(count)
    ]
    with (
        patch("app.services.literature_workflow.zotero_for_project", return_value=mock_svc),
        patch("app.api.zotero.zotero_service", mock_svc),
    ):
        res = await auth_client.post(
            f"/api/zotero/projects/{project_id}/import",
            json={
                "outline_heading": outline_heading,
                "source_query": "test query",
                "items": items,
            },
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body) == count
    assert all(row.get("confirmed_at") for row in body)
    return body, mock_svc
