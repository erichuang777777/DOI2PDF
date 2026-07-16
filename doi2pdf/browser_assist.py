from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any


CHALLENGE_MARKERS = (
    "just a moment",
    "performing security verification",
    "verify you are human",
    "validating you are human",
    "驗證您是人類",
    "正在執行安全驗證",
    "cloudflare",
)


def _looks_like_challenge(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in CHALLENGE_MARKERS)


async def open_url(
    url: str,
    profile_dir: Path,
    *,
    headless: bool = False,
    wait_for_console: bool = True,
    timeout_s: int = 180,
    poll_s: float = 3.0,
) -> dict[str, Any]:
    """Open a URL in browser-use using the user's local profile.

    This is an assist-only path. It keeps the browser visible so the user can
    manually complete any institution or publisher verification step, then
    returns the final URL/title for diagnostics.
    """

    try:
        from browser_use import Browser
    except ImportError as exc:  # pragma: no cover - runtime dependency gate
        raise RuntimeError("Install the browser-use extra first: pip install -e '.[browser_use]'") from exc

    browser = Browser(
        headless=headless,
        user_data_dir=str(profile_dir),
        profile_directory="Default",
        keep_alive=True,
        accept_downloads=True,
    )
    try:
        await browser.start()
        await browser.navigate_to(url)
        await asyncio.sleep(5)
        before = {
            "current_url": await browser.get_current_page_url(),
            "title": await browser.get_current_page_title(),
        }
        challenge_seen = False
        prompt_shown = False
        deadline = time.monotonic() + timeout_s
        final = before
        while True:
            state = await browser.get_state_as_text()
            title = await browser.get_current_page_title()
            current_url = await browser.get_current_page_url()
            final = {"current_url": current_url, "title": title}
            if not _looks_like_challenge(state) and not _looks_like_challenge(title):
                break
            challenge_seen = True
            if not wait_for_console:
                break
            if wait_for_console and not prompt_shown:
                prompt_shown = True
                await asyncio.to_thread(
                    input,
                    "Complete the browser verification in the visible window, then press Enter here... ",
                )
            if time.monotonic() >= deadline:
                break
            await asyncio.sleep(poll_s)
        if wait_for_console:
            await asyncio.sleep(1)
        after = {
            "current_url": final["current_url"],
            "title": final["title"],
        }
        return {
            "ok": True,
            "status": "session_ready" if not challenge_seen or not _looks_like_challenge(after["title"]) else "challenge_still_present",
            "challenge_seen": challenge_seen,
            "before": before,
            "after": after,
        }
    finally:
        await browser.close()
