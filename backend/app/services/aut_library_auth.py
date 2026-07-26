"""AUT Library / Shibboleth / Microsoft 登录（IEEE / ACM 共用）。"""

from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

SuccessCheck = Callable[[str], bool]


async def ensure_aut_logged_in(
    page,  # noqa: ANN001
    *,
    username: str,
    password: str,
    entry_url: str,
    already_ok: SuccessCheck,
    wait_url: Optional[SuccessCheck] = None,
) -> None:
    """
    若落在 IdP 登录页则填写 AUT 凭据；已在目标站则直接返回。

    Args:
        already_ok: 当前 URL 是否已进入目标库（无需登录）
        wait_url: 登录后等待的 URL 判定；默认与 already_ok 相同
    """
    wait_pred = wait_url or already_ok
    await page.wait_for_timeout(1500)
    url = (page.url or "").lower()

    if already_ok(url):
        return

    # --- Microsoft 多步：先邮箱再密码 ---
    ms_user = page.locator('input[name="loginfmt"]').first
    if await ms_user.count() > 0 and await ms_user.is_visible():
        await ms_user.fill(username)
        next_btn = page.locator("#idSIButton9, input[type='submit']").first
        if await next_btn.count() > 0:
            await next_btn.click()
            await page.wait_for_timeout(1500)
        ms_pass = page.locator('input[name="passwd"], input[type="password"]').first
        if await ms_pass.count() > 0 and await ms_pass.is_visible():
            await ms_pass.fill(password)
            submit = page.locator("#idSIButton9, input[type='submit']").first
            if await submit.count() > 0:
                await submit.click()
            await page.wait_for_load_state("domcontentloaded", timeout=90_000)
            await page.wait_for_timeout(2000)
            stay = page.locator("#idSIButton9, input[value='Yes']").first
            if await stay.count() > 0 and await stay.is_visible():
                await stay.click()
                await page.wait_for_timeout(1500)
        logger.info("已尝试 Microsoft 登录，当前 url=%s", page.url)
        if not already_ok((page.url or "").lower()):
            await page.goto(entry_url, wait_until="domcontentloaded", timeout=90_000)
            await page.wait_for_timeout(2000)
        return

    # --- AUT / Shibboleth 单页 ---
    user_loc = page.locator(
        'input#username, input[name="j_username"], input[name="username"]'
    ).first
    pass_loc = page.locator(
        'input#password, input[name="j_password"], input[name="password"], input[type="password"]'
    ).first

    if await user_loc.count() == 0 or not await user_loc.is_visible():
        logger.info("未检测到登录表单，当前 url=%s（可能已有会话）", page.url)
        return

    await user_loc.fill(username)
    if await pass_loc.count() > 0 and await pass_loc.is_visible():
        await pass_loc.fill(password)

    submit = page.locator(
        "#submitBtn, button#submitBtn, button[type='submit'], input[type='submit']"
    ).first
    if await submit.count() > 0:
        await submit.click()
    else:
        await pass_loc.press("Enter")

    try:
        await page.wait_for_url(
            lambda u: wait_pred((u or "").lower()),
            timeout=60_000,
        )
    except Exception:  # noqa: BLE001
        await page.wait_for_load_state("domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(5000)

    logger.info("已尝试 AUT/Shibboleth 登录，当前 url=%s", page.url)

    if not wait_pred((page.url or "").lower()):
        await page.goto(entry_url, wait_until="domcontentloaded", timeout=90_000)
        try:
            await page.wait_for_url(
                lambda u: wait_pred((u or "").lower()),
                timeout=45_000,
            )
        except Exception:  # noqa: BLE001
            await page.wait_for_timeout(3000)


def is_ieee_destination(url: str) -> bool:
    u = (url or "").lower()
    return "ieeexplore" in u or "ezproxy.aut.ac.nz" in u


def is_acm_destination(url: str) -> bool:
    u = (url or "").lower()
    return (
        "dl.acm.org" in u
        or "dl-acm-org" in u
        or ("acm" in u and "ezproxy.aut.ac.nz" in u)
        or "ezproxy.aut.ac.nz" in u
    )
