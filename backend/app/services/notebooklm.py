"""NotebookLM 同步服务：手动粘贴 + 连接本机 Chrome 抓取全量对话。"""

from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# 社区/既有自动化常用的消息选择器（Google 改版时优先改这里）
_MESSAGE_SELECTORS = [
    ".from-user-container .message-text-content",
    ".to-user-container .message-text-content",
    ".message-text-content",
    "[data-message-author]",
    "[data-turn-role]",
]

# 明显不是对话正文的 UI 文案
_UI_NOISE_RE = re.compile(
    r"^(Search results|No emoji found|Recently used|Loading(\.\.\.)?|"
    r"Emoji|Send|Share|Sources?|Studio|Chat|Notebook guide|"
    r"Add source|Upload|Copy|Download|Settings|Help|"
    r"Thinking(\.\.\.)?|Generating(\.\.\.)?|"
    r"\d+\s+sources?|Audio Overview|Mind Map|Report)$",
    re.I,
)

_PROFILE_IN_USE_HINT = (
    "无法连接可用的 Chrome 调试端口。\n"
    "新版 Chrome 会在「默认用户目录」上忽略 --remote-debugging-port。\n"
    "请按下列步骤：\n"
    "  1) Cmd+Q 完全退出所有 Chrome\n"
    "  2) 运行 ./scripts/start-chrome-debug.sh（会启动专用调试 Profile）\n"
    "  3) 在该窗口登录 Google 并打开 NotebookLM\n"
    "  4) 确认 .env 有 CHROME_CDP_URL=http://127.0.0.1:9222 后重启后端，再点「更新」"
)

# 在页面内执行：按 DOM 顺序抽取用户/助手消息
_EXTRACT_JS = """
() => {
  const noise = /^(Search results|No emoji found|Recently used|Loading|Emoji|Send|Share|Sources?|Studio|Chat|Notebook guide|Add source|Upload|Copy|Download|Settings|Help|Thinking|Generating|\\d+\\s+sources?|Audio Overview|Mind Map|Report)$/i;
  const blocks = [];

  const containers = document.querySelectorAll('.from-user-container, .to-user-container');
  if (containers.length) {
    containers.forEach((el) => {
      const role = el.classList.contains('from-user-container') ? 'User' : 'NotebookLM';
      const textEl = el.querySelector('.message-text-content') || el;
      const text = (textEl.innerText || '').trim();
      if (text && text.length > 1 && !noise.test(text)) {
        blocks.push(role + ':\\n' + text);
      }
    });
    if (blocks.length) return blocks.join('\\n\\n');
  }

  const msgs = document.querySelectorAll('.message-text-content, [data-message-author], [data-turn-role]');
  msgs.forEach((el) => {
    const text = (el.innerText || '').trim();
    if (text && text.length > 2 && !noise.test(text)) {
      blocks.push(text);
    }
  });
  if (blocks.length) return blocks.join('\\n\\n');

  // 最后尝试 chat / conversation 区域
  const region = document.querySelector('[role="log"], [aria-label*="chat" i], [aria-label*="conversation" i]');
  if (region) {
    const t = (region.innerText || '').trim();
    if (t.length > 40) return t;
  }
  return '';
}
"""


class NotebookLMService:
    """解析 NotebookLM 输入，或连接本机 Chrome 抓取全文。"""

    def extract_summary(self, raw_transcript: str, max_chars: int = 2000) -> str:
        """从对话全文中提取要点摘要。"""
        if not raw_transcript or not raw_transcript.strip():
            return ""

        lines = [ln.strip() for ln in raw_transcript.splitlines() if ln.strip()]
        constraints = [
            ln
            for ln in lines
            if re.match(r"^(constraint|requirement|必须|要求|约束)[:：\s]", ln, re.I)
        ]
        body = lines[:40]
        parts = []
        if constraints:
            parts.append("## Constraints\n" + "\n".join(f"- {c}" for c in constraints[:10]))
        parts.append("## Transcript Highlights\n" + "\n".join(body))
        summary = "\n\n".join(parts)
        return summary[:max_chars]

    def parse_markdown_file(self, content: str) -> Tuple[str, str]:
        """解析上传的 Markdown，返回 (raw_transcript, extracted_summary)。"""
        summary = self.extract_summary(content)
        return content, summary

    @staticmethod
    def _cdp_endpoint_alive(cdp_url: str) -> bool:
        """探测 Chrome 远程调试端口是否可用。"""
        base = cdp_url.rstrip("/")
        try:
            with urllib.request.urlopen(f"{base}/json/version", timeout=1.5) as resp:
                return 200 <= getattr(resp, "status", 200) < 300
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    def _resolve_cdp_url(self) -> Optional[str]:
        """优先使用配置的 CDP；否则尝试默认 9222。"""
        configured = (settings.chrome_cdp_url or "").strip()
        if configured:
            return configured
        default = "http://127.0.0.1:9222"
        if self._cdp_endpoint_alive(default):
            return default
        return None

    async def fetch_via_browser(self, notebook_url: str) -> str:
        """
        抓取策略（按优先级）：
        1. 连接已开启远程调试的当前 Chrome（CDP）——推荐，不抢 Profile 锁
        2. launch_persistent_context 独占打开 Profile（Chrome 必须完全退出）
        """
        url = (notebook_url or "").strip()
        if not url.startswith("http"):
            raise ValueError("notebook_url 无效，需为 http(s) 链接")

        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "未安装 playwright。请执行: pip install playwright && playwright install chrome"
            ) from exc

        cdp_url = self._resolve_cdp_url()
        async with async_playwright() as p:
            if cdp_url:
                if not self._cdp_endpoint_alive(cdp_url):
                    raise RuntimeError(
                        f"无法连接 Chrome 调试端口 {cdp_url}。\n"
                        "新版 Chrome 不会在默认 Profile 上开放调试端口。\n"
                        "请 Cmd+Q 退出 Chrome 后运行 ./scripts/start-chrome-debug.sh，"
                        "在弹出的专用窗口登录 NotebookLM，再重启后端并点「更新」。"
                    )
                logger.info("NotebookLM 经 CDP 抓取 url=%s cdp=%s", url, cdp_url)
                transcript = await self._fetch_with_cdp(p, url, cdp_url)
            else:
                logger.info("NotebookLM 经 persistent profile 抓取 url=%s", url)
                try:
                    transcript = await self._fetch_with_persistent_profile(p, url)
                except Exception as exc:  # noqa: BLE001
                    msg = str(exc)
                    if (
                        "existing browser session" in msg.lower()
                        or "already in use" in msg.lower()
                        or "profile is already in use" in msg.lower()
                    ):
                        raise RuntimeError(_PROFILE_IN_USE_HINT) from exc
                    raise

        text = self._normalize_transcript(transcript)
        text = self._strip_ui_noise(text)
        if not self._looks_like_conversation(text):
            raise RuntimeError(
                "未能抽到有效对话内容（上次常会抓到 Emoji/Search 等界面杂音）。\n"
                "请先在调试 Chrome 中手动打开该 Notebook，确认聊天记录已显示，"
                "关闭表情面板后，再回到平台点「更新」。"
            )
        logger.info("NotebookLM 抓取完成，字符数=%s", len(text))
        return text

    async def _fetch_with_cdp(self, playwright, url: str, cdp_url: str) -> str:  # noqa: ANN001
        """连接到正在运行的 Chrome；优先复用已打开的 Notebook 标签。"""
        browser = await playwright.chromium.connect_over_cdp(cdp_url)
        if not browser.contexts:
            raise RuntimeError("已连接 CDP，但未找到浏览器上下文，请重启带调试端口的 Chrome。")
        context = browser.contexts[0]
        page, created = await self._pick_or_open_notebook_page(context, url)
        try:
            await self._prepare_chat_view(page)
            await self._scroll_chat_history(page)
            return await self._extract_transcript(page)
        finally:
            if created:
                await page.close()

    async def _fetch_with_persistent_profile(self, playwright, url: str) -> str:  # noqa: ANN001
        """独占启动 Profile（要求该 Profile 当前未被 Chrome 使用）。"""
        user_data_dir = self._require_chrome_profile()
        profile = (settings.chrome_profile_directory or "Default").strip() or "Default"
        headless = bool(settings.notebooklm_headless)

        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            channel="chrome",
            headless=headless,
            args=[f"--profile-directory={profile}"],
            viewport={"width": 1400, "height": 900},
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            await self._prepare_chat_view(page)
            await self._scroll_chat_history(page)
            return await self._extract_transcript(page)
        finally:
            await context.close()

    async def _pick_or_open_notebook_page(self, context, url: str):  # noqa: ANN001
        """优先使用已打开的 notebooklm 标签（对话往往已加载）。"""
        target_id = self._notebook_id_from_url(url)
        for page in context.pages:
            page_url = page.url or ""
            if "notebooklm.google.com" not in page_url:
                continue
            if target_id and target_id in page_url:
                logger.info("复用已打开的 Notebook 标签: %s", page_url)
                return page, False
        for page in context.pages:
            if "notebooklm.google.com" in (page.url or ""):
                logger.info("复用 NotebookLM 标签并跳转到目标 URL")
                await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
                return page, False

        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        return page, True

    @staticmethod
    def _notebook_id_from_url(url: str) -> str:
        m = re.search(r"/notebook/([a-zA-Z0-9_-]+)", url)
        return m.group(1) if m else ""

    async def _prepare_chat_view(self, page) -> None:  # noqa: ANN001
        """关闭弹层、等待聊天区出现。"""
        await page.wait_for_timeout(2500)
        for _ in range(3):
            try:
                await page.keyboard.press("Escape")
            except Exception:  # noqa: BLE001
                pass
            await page.wait_for_timeout(300)

        # 尝试点到 Chat 区域（若有 Tab）
        for label in ("Chat", "聊天", "Conversation"):
            try:
                loc = page.get_by_role("tab", name=re.compile(label, re.I))
                if await loc.count():
                    await loc.first.click(timeout=1500)
                    await page.wait_for_timeout(800)
                    break
            except Exception:  # noqa: BLE001
                pass

        # 等待任一消息节点
        for selector in _MESSAGE_SELECTORS:
            try:
                await page.wait_for_selector(selector, timeout=5000)
                break
            except Exception:  # noqa: BLE001
                continue

    def _require_chrome_profile(self) -> Path:
        raw = (settings.chrome_user_data_dir or "").strip()
        if not raw:
            raise RuntimeError(
                "未配置 CHROME_CDP_URL，也未配置 CHROME_USER_DATA_DIR。\n"
                "推荐配置 CHROME_CDP_URL=http://127.0.0.1:9222 并运行 "
                "./scripts/start-chrome-debug.sh"
            )
        path = Path(raw).expanduser()
        if not path.exists():
            raise RuntimeError(f"Chrome 用户数据目录不存在: {path}")
        return path

    async def _scroll_chat_history(self, page) -> None:  # noqa: ANN001
        """在聊天容器内向上滚动，尽量加载完整历史。"""
        # 优先滚聊天容器，避免带动整个页面的 emoji/搜索面板
        scrolled = False
        for sel in (
            ".to-user-container",
            ".from-user-container",
            "[role='log']",
            "main",
        ):
            try:
                loc = page.locator(sel).first
                if await loc.count() == 0:
                    continue
                box = await loc.bounding_box()
                if not box:
                    continue
                x = box["x"] + box["width"] / 2
                y = box["y"] + min(box["height"], 200) / 2
                await page.mouse.move(x, y)
                for _ in range(20):
                    await page.mouse.wheel(0, -2400)
                    await page.wait_for_timeout(350)
                scrolled = True
                break
            except Exception:  # noqa: BLE001
                continue
        if not scrolled:
            for _ in range(15):
                await page.mouse.wheel(0, -2400)
                await page.wait_for_timeout(300)

    async def _extract_transcript(self, page) -> str:  # noqa: ANN001
        """抽取对话正文，过滤 UI 噪声。"""
        try:
            via_js = await page.evaluate(_EXTRACT_JS)
            if isinstance(via_js, str) and via_js.strip():
                return via_js.strip()
        except Exception as exc:  # noqa: BLE001
            logger.debug("evaluate 抽取失败: %s", exc)

        chunks: list[str] = []
        for selector in _MESSAGE_SELECTORS:
            try:
                loc = page.locator(selector)
                count = await loc.count()
                if count == 0:
                    continue
                for i in range(min(count, 500)):
                    try:
                        t = (await loc.nth(i).inner_text(timeout=1000)).strip()
                    except Exception:  # noqa: BLE001
                        continue
                    if t and not _UI_NOISE_RE.match(t):
                        chunks.append(t)
                if chunks:
                    return "\n\n".join(chunks)
            except Exception as exc:  # noqa: BLE001
                logger.debug("selector %s 失败: %s", selector, exc)

        # 不再回退到整页 body（极易抓到 emoji/搜索面板）
        return ""

    @classmethod
    def _strip_ui_noise(cls, text: str) -> str:
        lines = []
        for ln in (text or "").splitlines():
            s = ln.strip()
            if not s:
                lines.append("")
                continue
            if _UI_NOISE_RE.match(s):
                continue
            lines.append(ln.rstrip())
        return cls._normalize_transcript("\n".join(lines))

    @staticmethod
    def _looks_like_conversation(text: str) -> bool:
        """粗判是否像真实对话，而不是 UI 碎片。"""
        cleaned = (text or "").strip()
        if len(cleaned) < 80:
            return False
        # 全是噪声关键字则失败
        meaningful = [
            ln.strip()
            for ln in cleaned.splitlines()
            if ln.strip() and not _UI_NOISE_RE.match(ln.strip())
        ]
        if len("\n".join(meaningful)) < 80:
            return False
        junk_hits = sum(1 for ln in meaningful if _UI_NOISE_RE.match(ln))
        return junk_hits < max(1, len(meaningful) // 2)

    @staticmethod
    def _normalize_transcript(text: str) -> str:
        lines = [ln.rstrip() for ln in (text or "").splitlines()]
        out: list[str] = []
        blank = 0
        for ln in lines:
            if not ln.strip():
                blank += 1
                if blank <= 1:
                    out.append("")
                continue
            blank = 0
            out.append(ln)
        return "\n".join(out).strip()


notebooklm_service = NotebookLMService()
