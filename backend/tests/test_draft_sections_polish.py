"""分节 / 锁定 / 精修单元测试与 API。"""

from unittest.mock import patch
from uuid import UUID

from app.db.models import DraftWorking
from app.services.draft_sections import (
    apply_section_overrides,
    diff_sections,
    extract_locked_blocks,
    replace_section_in_markdown,
    restore_locked_blocks,
    split_markdown_sections,
)
from app.services import summarizer as summarizer_module
from tests.helpers import prepare_confirmed_literatures, prepare_writing_inputs


SAMPLE = """## Introduction

Hello world.

## Methods

See the table:

| A | B |
|---|---|
| 1 | 2 |

![fig](http://example.com/x.png)

More text.

## References

Smith, J. (2024). Title.
"""


def test_split_and_lock_detection():
    secs = split_markdown_sections(SAMPLE)
    assert [s.heading for s in secs] == ["Introduction", "Methods", "References"]
    methods = secs[1]
    assert methods.has_locked_blocks
    assert methods.locked_count >= 2
    extracted = extract_locked_blocks(methods.body)
    assert "<<LOCKED_0>>" in extracted.editable
    restored = restore_locked_blocks(extracted.editable, extracted.locked_blocks)
    assert "| A | B |" in restored
    assert "![fig]" in restored


def test_replace_section_and_overrides():
    new = "## Methods\n\nRewritten methods only.\n"
    out = replace_section_in_markdown(SAMPLE, "Methods", new)
    assert "Rewritten methods only" in out
    assert "Hello world" in out
    assert "| A | B |" not in out
    composed = apply_section_overrides(SAMPLE, {"Introduction": "## Introduction\n\nEdited intro.\n"})
    assert "Edited intro" in composed


def test_diff_marks_modified():
    base = "## A\n\nOne.\n\n## B\n\nTwo.\n"
    work = "## A\n\nOne changed.\n\n## B\n\nTwo.\n"
    items = diff_sections(base, work)
    by_h = {i.heading: i for i in items}
    assert by_h["A"].status == "modified"
    assert by_h["B"].status == "unchanged"


async def test_working_includes_sections_and_polish_accept(auth_client, session_factory):
    create = await auth_client.post("/api/projects", json={"title": "P1P2b"})
    pid = create.json()["id"]
    await prepare_writing_inputs(auth_client, pid)
    _lits, mock_svc = await prepare_confirmed_literatures(auth_client, pid, count=1)
    with (
        patch.object(summarizer_module, "has_openai_key", lambda: False),
        patch("app.services.literature_workflow.zotero_for_project", return_value=mock_svc),
    ):
        run = await auth_client.post(
            f"/api/projects/{pid}/run-agent",
            json={"max_papers": 1, "skip_search": True},
        )
    base = run.json()

    md = (
        "## Introduction\n\nHello.\n\n"
        "## Methods\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\nBody.\n"
    )
    async with session_factory() as session:
        w = DraftWorking(
            project_id=UUID(pid),
            base_version_id=UUID(base["id"]),
            content_markdown=md,
            section_overrides={},
            pending_directives=[],
            status="ACTIVE",
            source_filename="manual.md",
        )
        session.add(w)
        await session.commit()

    got = await auth_client.get(f"/api/drafts/{pid}/working")
    assert got.status_code == 200
    body = got.json()
    assert body["sections"]
    headings = [s["heading"] for s in body["sections"]]
    assert "Methods" in headings
    methods = next(s for s in body["sections"] if s["heading"] == "Methods")
    assert methods["has_locked_blocks"] is True

    diff = await auth_client.get(
        f"/api/drafts/{pid}/working/section-diff?heading=Introduction"
    )
    assert diff.status_code == 200
    assert "lines" in diff.json()

    fake_preview = {
        "heading": "Introduction",
        "preview_markdown": "## Introduction\n\nPolished hello.\n",
        "mode": "llm",
        "model": "gpt-4o-mini",
        "locked_count": 0,
        "openai_configured": True,
    }
    with patch("app.api.drafts.polish_section_markdown", return_value=fake_preview):
        prev = await auth_client.post(
            f"/api/drafts/{pid}/working/polish-section",
            json={"heading": "Introduction", "instruction": "Make clearer."},
        )
    assert prev.status_code == 200, prev.text
    assert "Polished" in prev.json()["preview_markdown"]

    acc = await auth_client.post(
        f"/api/drafts/{pid}/working/accept-section",
        json={
            "heading": "Introduction",
            "preview_markdown": "## Introduction\n\nPolished hello.\n",
            "instruction": "Make clearer.",
        },
    )
    assert acc.status_code == 200, acc.text
    wrk = acc.json()
    assert "Polished hello" in wrk["content_markdown"]
    assert wrk["section_overrides"].get("Introduction")
    assert wrk["pending_directives"]
    intro = next(s for s in wrk["sections"] if s["heading"] == "Introduction")
    assert intro["status"] == "polished"
    # M3：采纳上游后下游标 stale
    stale = [h.lower() for h in (wrk.get("stale_headings") or [])]
    assert "methods" in stale


def test_outline_seed_and_upstream_helpers():
    from app.services.draft_polish import (
        build_upstream_summaries,
        headings_after,
        match_outline_key_points,
        outline_seeds_map,
    )

    outline = [
        {"level": 1, "heading": "Introduction", "key_points": "Case: Acme Corp"},
        {"level": 1, "heading": "Methods", "key_points": "Four proposals A-D"},
    ]
    assert match_outline_key_points(outline, "introduction") == "Case: Acme Corp"
    assert outline_seeds_map(outline)["Methods"] == "Four proposals A-D"

    md = (
        "## Introduction\n\nHello Acme.\n\n"
        "## Methods\n\nDo research.\n\n"
        "## Discussion\n\nTalk.\n\n"
        "## References\n\nSmith (2020).\n"
    )
    up = build_upstream_summaries(md, "Methods")
    assert "Introduction" in up
    assert "Acme" in up
    after = headings_after(md, "Introduction")
    assert after == ["Methods", "Discussion"]


async def test_working_facts_and_multiturn_polish(auth_client, session_factory):
    create = await auth_client.post("/api/projects", json={"title": "M1M2"})
    pid = create.json()["id"]
    await prepare_writing_inputs(auth_client, pid)
    _lits, mock_svc = await prepare_confirmed_literatures(auth_client, pid, count=1)
    with (
        patch.object(summarizer_module, "has_openai_key", lambda: False),
        patch("app.services.literature_workflow.zotero_for_project", return_value=mock_svc),
    ):
        run = await auth_client.post(
            f"/api/projects/{pid}/run-agent",
            json={"max_papers": 1, "skip_search": True},
        )
    base = run.json()

    # 锁定大纲含 key_points
    async with session_factory() as session:
        from app.db.models import Project

        proj = await session.get(Project, UUID(pid))
        assert proj is not None
        proj.paper_outline = [
            {
                "level": 1,
                "heading": "Introduction",
                "key_points": "Case study: Northern Bank; proposals Alpha Beta",
            }
        ]
        w = DraftWorking(
            project_id=UUID(pid),
            base_version_id=UUID(base["id"]),
            content_markdown=(
                "## Introduction\n\nHello.\n\n"
                "## Methods\n\nBody.\n"
            ),
            section_overrides={},
            pending_directives=[],
            working_facts=None,
            stale_headings=[],
            status="ACTIVE",
            source_filename="manual.md",
        )
        session.add(w)
        await session.commit()

    facts = await auth_client.patch(
        f"/api/drafts/{pid}/working/facts",
        json={"working_facts": "Case = Northern Bank"},
    )
    assert facts.status_code == 200, facts.text
    assert facts.json()["working_facts"] == "Case = Northern Bank"
    assert facts.json()["outline_seeds"]["Introduction"].startswith("Case study")

    captured: dict = {}

    def _fake_polish(**kwargs):
        captured.update(kwargs)
        return {
            "heading": "Introduction",
            "preview_markdown": "## Introduction\n\nTurn2 text.\n",
            "mode": "llm",
            "model": "test-model",
            "locked_count": 0,
            "openai_configured": True,
        }

    with patch("app.api.drafts.polish_section_markdown", side_effect=_fake_polish):
        prev = await auth_client.post(
            f"/api/drafts/{pid}/working/polish-section",
            json={
                "heading": "Introduction",
                "instruction": "Continue polish",
                "base_markdown": "## Introduction\n\nTurn1 text.\n",
                "prior_instructions": ["Make clearer"],
            },
        )
    assert prev.status_code == 200, prev.text
    assert captured.get("base_markdown", "").startswith("## Introduction")
    assert "Northern Bank" in (captured.get("working_facts") or "")
    assert "Northern Bank" in (captured.get("outline_key_points") or "")
    assert captured.get("prior_instructions") == ["Make clearer"]
