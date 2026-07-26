"""共享 Playwright 会话工具：优先 Chrome CDP，否则独立启动 Chromium。"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
from typing import Optional, Tuple

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def cdp_endpoint_alive(cdp_url: str) -> bool:
    """探测 Chrome 远程调试端口是否可用。"""
    base = cdp_url.rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/json/version", timeout=1.5) as resp:
            return 200 <= getattr(resp, "status", 200) < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def resolve_cdp_url() -> Optional[str]:
    """优先配置的 CDP；否则尝试默认 9222。"""
    settings = get_settings()
    configured = (settings.chrome_cdp_url or "").strip()
    if configured:
        return configured
    default = "http://127.0.0.1:9222"
    if cdp_endpoint_alive(default):
        return default
    return None


async def open_page_via_cdp(playwright, url: str):  # noqa: ANN001
    """
    经 CDP 打开新标签页，返回 (browser, context, page)。

    调用方负责关闭 page；browser 为外部 Chrome，勿 disconnect 杀进程。
    """
    cdp_url = resolve_cdp_url()
    if not cdp_url:
        raise RuntimeError(
            "未配置可用的 CHROME_CDP_URL。请运行 ./scripts/start-chrome-debug.sh 后重试。"
        )
    if not cdp_endpoint_alive(cdp_url):
        raise RuntimeError(
            f"无法连接 Chrome 调试端口 {cdp_url}。\n"
            "请 Cmd+Q 退出 Chrome 后运行 ./scripts/start-chrome-debug.sh，再重试。"
        )
    browser = await playwright.chromium.connect_over_cdp(cdp_url)
    if not browser.contexts:
        raise RuntimeError("已连接 CDP，但未找到浏览器上下文，请重启带调试端口的 Chrome。")
    context = browser.contexts[0]
    page = await context.new_page()
    logger.info("CDP 打开页面 url=%s cdp=%s", url, cdp_url)
    await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
    return browser, context, page


async def open_page_for_automation(playwright, url: str) -> Tuple:  # noqa: ANN001
    """
    打开自动化页面。

    Returns:
        (browser, context, page, owns_browser)
        owns_browser=True 时调用方应在结束时 browser.close()。
    """
    cdp_url = resolve_cdp_url()
    if cdp_url and cdp_endpoint_alive(cdp_url):
        browser, context, page = await open_page_via_cdp(playwright, url)
        return browser, context, page, False

    logger.info("CDP 不可用，改用系统 Chrome 独立实例 url=%s", url)
    # channel=chrome：不依赖 playwright install；可与日常 Chrome 并存
    browser = await playwright.chromium.launch(headless=False, channel="chrome")
    context = await browser.new_context(viewport={"width": 1400, "height": 900})
    page = await context.new_page()
    await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
    return browser, context, page, True
