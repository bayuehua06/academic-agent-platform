"""证据卡 / grounding formatter 测试。"""

from types import SimpleNamespace

import pytest

from app.services.evidence_cards import (
    build_evidence_cards,
    extract_pdf_text,
    format_allowed_sources_with_evidence,
    select_evidence_excerpt,
)


def test_select_evidence_excerpt_prefers_matching_chunks(monkeypatch):
    monkeypatch.setattr(
        "app.services.evidence_cards.settings.writer_evidence_best_score_min", 2
    )
    monkeypatch.setattr(
        "app.services.evidence_cards.settings.writer_evidence_top_k", 2
    )
    src = {
        "title": "Paper A",
        "abstract": "Short abstract fallback.",
        "evidence_text": (
            "This paragraph is generic.\n\n"
            "Cost and feasibility improved after deployment in higher education.\n\n"
            "Another chunk mentions feasibility and risk for implementation."
        ),
        "evidence_tier": "full_resource",
        "evidence_source": "landing",
    }
    picked = select_evidence_excerpt(
        src,
        heading="Evaluation",
        key_points="cost risk feasibility higher education",
    )
    assert picked["tier"] == "full_resource"
    assert "feasibility" in picked["excerpt"].lower()
    assert picked["fallback"] is False


def test_select_evidence_excerpt_falls_back_to_abstract(monkeypatch):
    monkeypatch.setattr(
        "app.services.evidence_cards.settings.writer_evidence_best_score_min", 3
    )
    src = {
        "title": "Paper B",
        "abstract": "This abstract discusses platform governance.",
        "evidence_text": "Only one weak keyword appears here: cost.",
        "evidence_tier": "full_resource",
        "evidence_source": "landing",
    }
    picked = select_evidence_excerpt(
        src,
        heading="Governance",
        key_points="platform governance policy accountability",
    )
    assert picked["tier"] == "abstract"
    assert "platform governance" in picked["excerpt"].lower()
    assert picked["fallback"] is True


def test_format_allowed_sources_with_evidence_marks_metadata_only():
    text = format_allowed_sources_with_evidence(
        [
            {
                "title": "Paper C",
                "authors": ["Smith, J."],
                "year": "2024",
                "doi": "10.1000/x",
                "abstract": "",
                "evidence_text": "",
            }
        ],
        heading="Methods",
        key_points="methods design",
    )
    assert "tier=metadata_only" in text
    assert "do not invent findings" in text.lower()


async def test_build_evidence_cards_keeps_local_abstract_without_network():
    cards = await build_evidence_cards(
        [
            {
                "title": "Paper D",
                "authors": ["Smith, J."],
                "year": "2024",
                "doi": "10.1000/d",
                "abstract": "Local abstract already exists.",
            }
        ]
    )
    assert cards[0]["abstract"] == "Local abstract already exists."
    assert cards[0]["evidence_tier"] == "abstract"
    assert cards[0]["evidence_source"] in {"zotero", "none"}


def test_extract_pdf_text_empty_bytes():
    assert extract_pdf_text(b"") == ""
    assert extract_pdf_text(b"not-a-pdf") == ""


@pytest.mark.asyncio
async def test_build_evidence_cards_prefers_zotero_pdf(monkeypatch):
    monkeypatch.setattr(
        "app.services.evidence_cards.settings.writer_evidence_enable_zotero_pdf", True
    )
    monkeypatch.setattr(
        "app.services.evidence_cards.settings.writer_evidence_enable_unpaywall", False
    )

    class FakeZot:
        is_configured = True

    import importlib

    zot_mod = importlib.import_module("app.services.zotero_service")
    monkeypatch.setattr(zot_mod, "zotero_for_project", lambda project: FakeZot())

    async def fake_zotero_pdf(zot_svc, item_key):
        assert item_key == "ITEM1"
        assert zot_svc is not None
        return (
            "Cost and feasibility improved after deployment in higher education. "
            "Risk mitigation was evaluated carefully."
        )

    monkeypatch.setattr(
        "app.services.evidence_cards._fetch_zotero_pdf_text",
        fake_zotero_pdf,
    )

    cards = await build_evidence_cards(
        [
            {
                "title": "Paper E",
                "authors": ["Lee, A."],
                "year": "2023",
                "doi": "10.1000/e",
                "abstract": "Local abstract should be overridden by PDF tier.",
                "zotero_item_key": "ITEM1",
            }
        ],
        project=SimpleNamespace(zotero_library_id="1", zotero_library_type="user"),
    )
    assert cards[0]["evidence_tier"] == "full_resource"
    assert cards[0]["evidence_source"] == "zotero_pdf"
    assert "feasibility" in cards[0]["evidence_text"].lower()


@pytest.mark.asyncio
async def test_build_evidence_cards_unpaywall_fallback(monkeypatch):
    monkeypatch.setattr(
        "app.services.evidence_cards.settings.writer_evidence_enable_zotero_pdf", False
    )
    monkeypatch.setattr(
        "app.services.evidence_cards.settings.writer_evidence_enable_unpaywall", True
    )
    monkeypatch.setattr(
        "app.services.evidence_cards.settings.writer_evidence_unpaywall_email",
        "dev@example.com",
    )

    async def fake_unpaywall(doi, client):
        assert doi == "10.1000/u"
        return "Open access full text about digital platforms transformation and cost."

    monkeypatch.setattr(
        "app.services.evidence_cards._fetch_unpaywall_pdf_text",
        fake_unpaywall,
    )

    cards = await build_evidence_cards(
        [
            {
                "title": "Paper U",
                "authors": ["Ng, B."],
                "year": "2022",
                "doi": "10.1000/u",
                "abstract": "",
            }
        ]
    )
    assert cards[0]["evidence_tier"] == "full_resource"
    assert cards[0]["evidence_source"] == "unpaywall"
    assert "platforms" in cards[0]["evidence_text"].lower()


@pytest.mark.asyncio
async def test_build_evidence_cards_skips_unpaywall_without_email(monkeypatch):
    monkeypatch.setattr(
        "app.services.evidence_cards.settings.writer_evidence_enable_zotero_pdf", False
    )
    monkeypatch.setattr(
        "app.services.evidence_cards.settings.writer_evidence_enable_unpaywall", True
    )
    monkeypatch.setattr(
        "app.services.evidence_cards.settings.writer_evidence_unpaywall_email", ""
    )

    called = {"n": 0}

    async def fake_unpaywall(doi, client):
        called["n"] += 1
        return "should not run"

    monkeypatch.setattr(
        "app.services.evidence_cards._fetch_unpaywall_pdf_text",
        fake_unpaywall,
    )

    cards = await build_evidence_cards(
        [
            {
                "title": "Paper V",
                "authors": ["Ng, B."],
                "year": "2022",
                "doi": "10.1000/v",
                "abstract": "Only abstract available.",
            }
        ]
    )
    assert called["n"] == 0
    assert cards[0]["evidence_tier"] == "abstract"


@pytest.mark.asyncio
async def test_build_evidence_cards_reuses_cached_fulltext(monkeypatch):
    """已有 evidence_text + 匹配 content_key 时跳过 URL/PDF/Unpaywall。"""
    monkeypatch.setattr(
        "app.services.evidence_cards.settings.writer_evidence_force_refresh", False
    )
    monkeypatch.setattr(
        "app.services.evidence_cards.settings.writer_evidence_enable_zotero_pdf", True
    )
    monkeypatch.setattr(
        "app.services.evidence_cards.settings.writer_evidence_enable_unpaywall", True
    )
    monkeypatch.setattr(
        "app.services.evidence_cards.settings.writer_evidence_unpaywall_email",
        "dev@example.com",
    )

    calls = {"url": 0, "zot": 0, "unpay": 0}

    async def boom_url(url, client):
        calls["url"] += 1
        raise AssertionError("should not fetch url")

    async def boom_zot(zot_svc, item_key):
        calls["zot"] += 1
        raise AssertionError("should not fetch zotero pdf")

    async def boom_unpay(doi, client):
        calls["unpay"] += 1
        raise AssertionError("should not fetch unpaywall")

    monkeypatch.setattr("app.services.evidence_cards._fetch_url_text", boom_url)
    monkeypatch.setattr("app.services.evidence_cards._fetch_zotero_pdf_text", boom_zot)
    monkeypatch.setattr(
        "app.services.evidence_cards._fetch_unpaywall_pdf_text", boom_unpay
    )

    cached = (
        "Cached full text about cost feasibility and higher education deployment."
    )
    src = {
        "title": "Paper Cache",
        "authors": ["Cached, A."],
        "year": "2021",
        "doi": "10.1000/cache",
        "abstract": "Old abstract",
        "landing_url": "https://example.com/paper",
        "zotero_item_key": "ITEMC",
        "evidence_text": cached,
        "evidence_tier": "full_resource",
        "evidence_source": "zotero_pdf",
        "evidence_content_key": "z:ITEMC|u:https://example.com/paper|d:10.1000/cache",
    }
    cards = await build_evidence_cards([src], project=SimpleNamespace())
    assert calls == {"url": 0, "zot": 0, "unpay": 0}
    assert cards[0]["evidence_tier"] == "full_resource"
    assert cards[0]["evidence_text"] == cached
    assert "cost" in cards[0]["evidence_text"].lower()

    # 按章摘录仍现算（不同 heading 可选出不同片段）
    picked = select_evidence_excerpt(
        cards[0],
        heading="Evaluation",
        key_points="cost feasibility higher education",
    )
    assert picked["tier"] == "full_resource"
    assert "feasibility" in picked["excerpt"].lower()


@pytest.mark.asyncio
async def test_build_evidence_cards_invalid_cache_key_refetches(monkeypatch):
    monkeypatch.setattr(
        "app.services.evidence_cards.settings.writer_evidence_force_refresh", False
    )
    monkeypatch.setattr(
        "app.services.evidence_cards.settings.writer_evidence_enable_zotero_pdf", False
    )
    monkeypatch.setattr(
        "app.services.evidence_cards.settings.writer_evidence_enable_unpaywall", False
    )

    async def fake_url(url, client):
        assert url == "https://example.com/new"
        return "Fresh landing page text about platforms."

    monkeypatch.setattr("app.services.evidence_cards._fetch_url_text", fake_url)

    cards = await build_evidence_cards(
        [
            {
                "title": "Paper Stale",
                "doi": "10.1000/stale",
                "landing_url": "https://example.com/new",
                "evidence_text": "Stale cached text that should be ignored.",
                "evidence_tier": "full_resource",
                "evidence_source": "landing",
                # key 仍指向旧 URL → 失效
                "evidence_content_key": "z:|u:https://example.com/old|d:10.1000/stale",
            }
        ]
    )
    assert cards[0]["evidence_source"] == "landing"
    assert "Fresh landing" in cards[0]["evidence_text"]
    assert cards[0]["evidence_content_key"] == (
        "z:|u:https://example.com/new|d:10.1000/stale"
    )


@pytest.mark.asyncio
async def test_persist_evidence_backfill_writes_evidence_text(session_factory):
    from uuid import uuid4

    from app.core.security import get_password_hash
    from app.db.models import Literature, Project, User
    from app.services.evidence_cards import persist_evidence_backfill

    async with session_factory() as db:
        user = User(
            username=f"u_{uuid4().hex[:8]}",
            email=f"{uuid4().hex[:8]}@ex.com",
            password_hash=get_password_hash("pass1234"),
        )
        db.add(user)
        await db.flush()
        project = Project(user_id=user.id, title="Evidence Cache Proj", status="DRAFT")
        db.add(project)
        await db.flush()
        lit = Literature(
            project_id=project.id,
            zotero_item_key="ITEMX",
            title="Cached Paper",
            authors=["A"],
            year="2020",
            doi="10.1000/x",
            selected_for_draft=True,
        )
        db.add(lit)
        await db.flush()

        await persist_evidence_backfill(
            project.id,
            db,
            [
                {
                    "zotero_item_key": "ITEMX",
                    "title": "Cached Paper",
                    "doi": "10.1000/x",
                    "abstract": "Abs from enrich",
                    "landing_url": "https://example.com/x",
                    "evidence_text": "Full extracted text here.",
                    "evidence_tier": "full_resource",
                    "evidence_source": "zotero_pdf",
                    "evidence_content_key": "z:ITEMX|u:https://example.com/x|d:10.1000/x",
                }
            ],
        )
        await db.refresh(lit)
        assert lit.evidence_text == "Full extracted text here."
        assert lit.evidence_tier == "full_resource"
        assert lit.evidence_source == "zotero_pdf"
        assert lit.evidence_content_key.startswith("z:ITEMX")
        assert lit.abstract == "Abs from enrich"
        assert lit.evidence_fetched_at is not None
        await db.commit()
