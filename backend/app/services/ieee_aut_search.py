"""AUT Library → IEEE Xplore 文献检索（Playwright + Chrome CDP）。"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

from app.core.config import get_settings
from app.services.aut_library_auth import ensure_aut_logged_in, is_ieee_destination
from app.services.browser_cdp import open_page_for_automation
from app.services.literature_providers import get_provider_registry

logger = logging.getLogger(__name__)

_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)


class IeeeAutSearchService:
    """经 AUT 图书馆入口进入 IEEE，并解析检索结果。"""

    @property
    def _settings(self):
        return get_settings()

    @property
    def entry_url(self) -> str:
        return get_provider_registry()["ieee"].entry_url

    @property
    def is_aut_configured(self) -> bool:
        return bool(self._settings.aut_username and self._settings.aut_password)

    async def ping(self) -> Dict[str, Any]:
        """探测能否进入 IEEE（含必要登录）。"""
        if not self.is_aut_configured:
            return {
                "ok": False,
                "provider": "ieee",
                "configured": False,
                "error": "未配置 AUT_USERNAME / AUT_PASSWORD",
            }
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            return {
                "ok": False,
                "provider": "ieee",
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
                    ok = (
                        "ieee" in final_url.lower()
                        or "ezproxy.aut.ac.nz" in final_url.lower()
                        or await self._looks_like_ieee(page)
                    )
                    return {
                        "ok": ok,
                        "provider": "ieee",
                        "configured": True,
                        "final_url": final_url,
                        "error": None if ok else "未能确认已进入 IEEE Xplore",
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
            logger.warning("IEEE ping 失败: %s", exc)
            return {
                "ok": False,
                "provider": "ieee",
                "configured": True,
                "error": str(exc),
            }

    async def search(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        用给定 query 检索 IEEE，返回候选列表。

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
        """若落在 IdP / Shibboleth / Microsoft 登录页则填写 AUT 凭据。"""
        if await self._looks_like_ieee(page):
            return
        await ensure_aut_logged_in(
            page,
            username=self._settings.aut_username,
            password=self._settings.aut_password,
            entry_url=self.entry_url,
            already_ok=is_ieee_destination,
        )

    async def _looks_like_ieee(self, page) -> bool:  # noqa: ANN001
        url = (page.url or "").lower()
        if is_ieee_destination(url):
            return True
        title = (await page.title() or "").lower()
        return "ieee" in title and ("xplore" in title or "loading" in title)

    async def _run_search(self, page, query: str) -> None:  # noqa: ANN001
        """在 IEEE 执行检索。"""
        # 优先经 ezproxy（若已有会话）；否则直达公网结果页
        current = page.url or ""
        if "ezproxy.aut.ac.nz" in current.lower():
            search_url = (
                "https://ieeexplore-ieee-org.ezproxy.aut.ac.nz/search/searchresult.jsp"
                f"?newsearch=true&queryText={quote_plus(query)}"
            )
        else:
            search_url = (
                "https://ieeexplore.ieee.org/search/searchresult.jsp"
                f"?newsearch=true&queryText={quote_plus(query)}"
            )
        await page.goto(search_url, wait_until="domcontentloaded", timeout=90_000)
        await page.wait_for_timeout(2500)

        # 若被踢回登录，再试一次
        if "login.aut.ac.nz" in (page.url or "").lower() or "microsoftonline" in (
            page.url or ""
        ).lower():
            await self._ensure_logged_in(page)
            await page.goto(search_url, wait_until="domcontentloaded", timeout=90_000)
            await page.wait_for_timeout(2500)

    async def _parse_results(self, page, max_results: int) -> List[Dict[str, Any]]:  # noqa: ANN001
        """解析 IEEE 结果列表（选择器尽力兼容）。"""
        # 等待结果卡片
        candidates_selectors = [
            "xpl-results-item",
            ".List-results-items > div",
            "div.List-results-items div[class*='result']",
            ".result-item",
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
            # 兜底：从页面文本里抓标题链接
            logger.warning("未匹配到 IEEE 结果选择器，尝试链接兜底")
            links = page.locator('a[href*="/document/"]')
            count = await links.count()
            for i in range(min(count, max_results)):
                a = links.nth(i)
                title = (await a.inner_text() or "").strip()
                href = await a.get_attribute("href")
                if not title or len(title) < 5:
                    continue
                url = href if (href or "").startswith("http") else f"https://ieeexplore.ieee.org{href}"
                items.append(
                    {
                        "title": title,
                        "authors": [],
                        "year": None,
                        "doi": None,
                        "abstract": None,
                        "url": url,
                        "provider": "ieee",
                    }
                )
            return items

        cards = page.locator(found_sel)
        count = await cards.count()
        for i in range(min(count, max_results)):
            card = cards.nth(i)
            text = (await card.inner_text() or "").strip()
            title = ""
            href = None
            title_loc = card.locator("a[href*='/document/'], h2 a, .result-item-title a").first
            if await title_loc.count() > 0:
                title = (await title_loc.inner_text() or "").strip()
                href = await title_loc.get_attribute("href")
            if not title:
                lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                title = lines[0] if lines else "Untitled"

            doi = None
            m = _DOI_RE.search(text)
            if m:
                doi = m.group(0).rstrip(".")

            year = None
            ym = re.search(r"\b(19|20)\d{2}\b", text)
            if ym:
                year = ym.group(0)

            authors: List[str] = []
            author_loc = card.locator(
                ".author, .authors, xpl-authors, [class*='author']"
            ).first
            if await author_loc.count() > 0:
                author_text = (await author_loc.inner_text() or "").strip()
                authors = [a.strip() for a in re.split(r"[;|]", author_text) if a.strip()][:8]

            abstract = None
            abs_loc = card.locator(".abstract, [class*='abstract']").first
            if await abs_loc.count() > 0:
                abstract = (await abs_loc.inner_text() or "").strip()[:2000] or None

            url = None
            if href:
                url = href if href.startswith("http") else f"https://ieeexplore.ieee.org{href}"

            items.append(
                {
                    "title": title,
                    "authors": authors,
                    "year": year,
                    "doi": doi,
                    "abstract": abstract,
                    "url": url,
                    "provider": "ieee",
                }
            )
        return items


ieee_aut_search_service = IeeeAutSearchService()
