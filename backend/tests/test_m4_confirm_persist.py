"""M4/P3：确认落库 directives/Facts、References 重建、指令 CRUD。"""

from unittest.mock import patch
from uuid import UUID

from app.db.models import DraftWorking
from app.services.references_rebuild import (
    iter_intext_citation_keys,
    rebuild_apa_references_from_citations,
)
from app.services import summarizer as summarizer_module
from tests.helpers import prepare_confirmed_literatures, prepare_writing_inputs


def test_rebuild_references_matches_intext():
    md = (
        "## Intro\n\n"
        "Platformization matters (Smith, 2024). "
        "Also Fake Author (1999) invented this.\n"
    )
    sources = [
        {
            "title": "Real Paper",
            "authors": ["Smith, J."],
            "year": "2024",
            "doi": "10.1/x",
        }
    ]
    keys = iter_intext_citation_keys(md)
    assert ("smith", "2024") in keys
    body, refs, unmatched, n = rebuild_apa_references_from_citations(md, sources)
    assert n == 1
    assert "Smith" in refs
    assert "Real Paper" in refs or "Real" in refs
    assert any("fake" in u.lower() or "1999" in u for u in unmatched)
    assert "## Intro" in body


async def test_confirm_persists_directives_facts_and_refs(auth_client, session_factory):
    create = await auth_client.post("/api/projects", json={"title": "M4P3"})
    pid = create.json()["id"]
    await prepare_writing_inputs(auth_client, pid)
    lits, mock_svc = await prepare_confirmed_literatures(auth_client, pid, count=1)
    with (
        patch.object(summarizer_module, "has_openai_key", lambda: False),
        patch("app.services.literature_workflow.zotero_for_project", return_value=mock_svc),
    ):
        run = await auth_client.post(
            f"/api/projects/{pid}/run-agent",
            json={"max_papers": 1, "skip_search": True},
        )
    base = run.json()
    lit = lits[0]
    # helpers 里作者是 "Author 1"；文内引用需可解析姓氏（≥2 字母）
    surname = "Smith"
    year = lit.get("year") or "2020"

    md = (
        f"## Introduction\n\nCite ({surname}, {year}).\n\n"
        "## Methods\n\nBody.\n"
    )
    async with session_factory() as session:
        from app.db.models import Literature

        # 把库中文献作者改成可匹配的 Smith
        lit_row = await session.get(Literature, UUID(lit["id"]))
        assert lit_row is not None
        lit_row.authors = ["Smith, J."]
        lit_row.year = year

        w = DraftWorking(
            project_id=UUID(pid),
            base_version_id=UUID(base["id"]),
            content_markdown=md,
            section_overrides={},
            pending_directives=[
                {
                    "outline_heading": "Introduction",
                    "directive_text": "[Section: Introduction] Emphasize platforms.",
                    "instruction": "Emphasize platforms.",
                },
                {
                    "outline_heading": "Methods",
                    "directive_text": "[Section: Methods] [manual edit] skip",
                    "instruction": "[manual edit] User edited",
                },
            ],
            working_facts="Case = Northern Bank",
            stale_headings=[],
            status="ACTIVE",
            source_filename="m4.md",
        )
        session.add(w)
        await session.commit()

    conf = await auth_client.post(f"/api/drafts/{pid}/working/confirm")
    assert conf.status_code == 200, conf.text
    body = conf.json()
    assert body["directives_persisted"] == 1
    assert body.get("references_matched", 0) >= 1
    assert "Smith" in (body.get("apa_references_block") or "")

    dirs = await auth_client.get(f"/api/projects/{pid}/section-directives")
    assert dirs.status_code == 200
    rows = dirs.json()
    assert len(rows) == 1
    assert rows[0]["outline_heading"] == "Introduction"
    assert "platforms" in rows[0]["directive_text"].lower()

    proj = await auth_client.get(f"/api/projects/{pid}")
    assert "Northern Bank" in (proj.json().get("confirmed_facts") or "")

    # 软删
    did = rows[0]["id"]
    de = await auth_client.delete(f"/api/projects/{pid}/section-directives/{did}")
    assert de.status_code == 204
    dirs2 = await auth_client.get(f"/api/projects/{pid}/section-directives")
    assert dirs2.json() == []

    # 新工作区应预填 Facts
    start = await auth_client.post(
        f"/api/drafts/{pid}/working/start",
        params={"base_version_id": body["id"]},
    )
    assert start.status_code == 201, start.text
    assert "Northern Bank" in (start.json().get("working_facts") or "")
