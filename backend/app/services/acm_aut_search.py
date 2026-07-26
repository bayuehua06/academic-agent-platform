"""AUT Library → ACM Digital Library 文献检索（Playwright + Chrome CDP）。"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List
from urllib.parse import quote_plus

from app.core.config import get_settings
from app.services.aut_library_auth import ensure_aut_logged_in, is_acm_destination
from app.services.browser_cdp import open_page_for_automation
from app.services.literature_providers import get_provider_registry

logger = logging.getLogger(__name__)

_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)


def _acm_ok(url: str) -> bool:
    """登录后 / ping 成功判定（含 ezproxy 包装的 ACM）。"""
    u = (url or "").lower()
    if is_acm_destination(u):
        return True
    return "ezproxy.aut.ac.nz" in u


class AcmAutSearchService:
    """经 AUT 图书馆入口进入 ACM DL，并解析检索结果。"""

    @property
    def _settings(self):
        return get_settings()

    @property
    def entry_url(self) -> str:
        return get_provider_registry()["acm"].entry_url

    @property
    def is_aut_configured(self) -> bool:
        return bool(self._settings.aut_username and self._settings.aut_password)

    async def ping(self) -> Dict[str, Any]:
        """探测能否进入 ACM（含必要登录）。"""
        if not self.is_aut_configured:
            return {
                "ok": False,
                "provider": "acm",
                "configured": False,
                "error": "未配置 AUT_USERNAME / AUT_PASSWORD",
            }
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            return {
                "ok": False,
                "provider": "acm",
                "configured": True,
                "error": f"未安装 playwright: {exc}",
            }

        try:
            async with async_playwright() as p:
                browser, _, page, owns_browser = await open_page_for_automation(
                    p, self.entry_url
                )
                try:
                    await self._ensure_logged_in(page)
                    final_url = page.url or ""
                    ok = _acm_ok(final_url) or await self._looks_like_acm(page)
                    return {
                        "ok": ok,
                        "provider": "acm",
                        "configured": True,
                        "final_url": final_url,
                        "error": None if ok else "未能确认已进入 ACM Digital Library",
                    }
                finally:
                    try:
                        await page.close()
                    except Exception:  # noqa: BLE001
                        pass
                    if owns_browser:
                        try:
                            await browser.close()
                        except Exception:  # noqa: BLE001
                            pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("ACM ping 失败: %s", exc)
            return {
                "ok": False,
                "provider": "acm",
                "configured": True,
                "error": str(exc),
            }

    async def search(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        用给定 query 检索 ACM，返回候选列表。

        每项尽量含 title / authors / year / doi / abstract / url。
        """
        q = (query or "").strip()
        if not q:
            raise ValueError("检索词不能为空")
        if not self.is_aut_configured:
            raise RuntimeError("未配置 AUT_USERNAME / AUT_PASSWORD")

        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "未安装 playwright。请执行: pip install playwright && playwright install chrome"
            ) from exc

        async with async_playwright() as p:
            browser, _, page, owns_browser = await open_page_for_automation(
                p, self.entry_url
            )
            try:
                await self._ensure_logged_in(page)
                await self._run_search(page, q)
                return await self._parse_results(page, max_results=max_results)
            finally:
                try:
                    await page.close()
                except Exception:  # noqa: BLE001
                    pass
                if owns_browser:
                    try:
                        await browser.close()
                    except Exception:  # noqa: BLE001
                        pass

    async def _ensure_logged_in(self, page) -> None:  # noqa: ANN001
        if await self._looks_like_acm(page):
            return
        await ensure_aut_logged_in(
            page,
            username=self._settings.aut_username,
            password=self._settings.aut_password,
            entry_url=self.entry_url,
            already_ok=_acm_ok,
        )

    async def _looks_like_acm(self, page) -> bool:  # noqa: ANN001
        url = (page.url or "").lower()
        if is_acm_destination(url) or "ezproxy.aut.ac.nz" in url:
            return True
        title = (await page.title() or "").lower()
        return "acm" in title and ("digital" in title or "library" in title or "search" in title)

    async def _run_search(self, page, query: str) -> None:  # noqa: ANN001
        """在 ACM DL 执行检索。"""
        current = page.url or ""
        if "ezproxy.aut.ac.nz" in current.lower():
            search_url = (
                "https://dl-acm-org.ezproxy.aut.ac.nz/action/doSearch"
                f"?AllField={quote_plus(query)}&pageSize=20"
            )
        else:
            search_url = (
                "https://dl.acm.org/action/doSearch"
                f"?AllField={quote_plus(query)}&pageSize=20"
            )
        await page.goto(search_url, wait_until="domcontentloaded", timeout=90_000)
        await page.wait_for_timeout(2500)

        if "login.aut.ac.nz" in (page.url or "").lower() or "microsoftonline" in (
            page.url or ""
        ).lower():
            await self._ensure_logged_in(page)
            await page.goto(search_url, wait_until="domcontentloaded", timeout=90_000)
            await page.wait_for_timeout(2500)

    async def _parse_results(self, page, max_results: int) -> List[Dict[str, Any]]:  # noqa: ANN001
        """解析 ACM 结果列表（选择器尽力兼容）。"""
        candidates_selectors = [
            ".search__item.issue-item-container",
            ".issue-item-container",
            "li.search__item",
            ".issue-item",
        ]
        found_sel = None
        for sel in candidates_selectors:
            try:
                await page.wait_for_selector(sel, timeout=8_000)
                found_sel = sel
                break
            except Exception:  # noqa: BLE001
                continue

        items: List[Dict[str, Any]] = []
        if not found_sel:
            logger.warning("未匹配到 ACM 结果选择器，尝试链接兜底")
            links = page.locator('a[href*="/doi/"]')
            count = await links.count()
            for i in range(min(count, max_results * 2)):
                a = links.nth(i)
                title = (await a.inner_text() or "").strip()
                href = await a.get_attribute("href")
                if not title or len(title) < 5:
                    continue
                if href and "/doi/" not in href:
                    continue
                url = href if (href or "").startswith("http") else f"https://dl.acm.org{href}"
                doi = None
                if href:
                    m = _DOI_RE.search(href)
                    if m:
                        doi = m.group(0)
                items.append(
                    {
                        "title": title,
                        "authors": [],
                        "year": None,
                        "doi": doi,
                        "abstract": None,
                        "url": url,
                        "provider": "acm",
                    }
                )
                if len(items) >= max_results:
                    break
            return items

        cards = page.locator(found_sel)
        count = await cards.count()
        for i in range(min(count, max_results)):
            card = cards.nth(i)
            text = (await card.inner_text() or "").strip()
            title = ""
            href = None
            title_loc = card.locator(
                "h5 a, .issue-item__title a, a[href*='/doi/'], .hlFld-Title a"
            ).first
            if await title_loc.count() > 0:
                title = (await title_loc.inner_text() or "").strip()
                href = await title_loc.get_attribute("href")
            if not title:
                lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                title = lines[0] if lines else "Untitled"

            doi = None
            if href:
                m = _DOI_RE.search(href)
                if m:
                    doi = m.group(0)
            if not doi:
                m = _DOI_RE.search(text)
                if m:
                    doi = m.group(0).rstrip(".")

            year = None
            ym = re.search(r"\b(19|20)\d{2}\b", text)
            if ym:
                year = ym.group(0)

            authors: List[str] = []
            author_loc = card.locator(
                ".issue-item__detail ul, .rlist--inline.comma, "
                "[class*='author'], .loa__author-name"
            ).first
            if await author_loc.count() > 0:
                author_text = (await author_loc.inner_text() or "").strip()
                authors = [
                    a.strip()
                    for a in re.split(r"[,;|]", author_text)
                    if a.strip() and len(a.strip()) > 1
                ][:8]

            abstract = None
            abs_loc = card.locator(
                ".issue-item__abstract, .abstract, [class*='abstract']"
            ).first
            if await abs_loc.count() > 0:
                abstract = (await abs_loc.inner_text() or "").strip()[:2000] or None

            url = None
            if href:
                url = href if href.startswith("http") else f"https://dl.acm.org{href}"

            items.append(
                {
                    "title": title,
                    "authors": authors,
                    "year": year,
                    "doi": doi,
                    "abstract": abstract,
                    "url": url,
                    "provider": "acm",
                }
            )
        return items


acm_aut_search_service = AcmAutSearchService()
