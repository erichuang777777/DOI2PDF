from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .http import looks_like_challenge_text


def _safe_url(value: str) -> str:
    """Return only scheme/host/path; never emit credentials or signed queries."""
    parts = urlsplit(value)
    host = parts.hostname or ""
    try:
        if parts.port:
            host += f":{parts.port}"
    except ValueError:
        pass
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


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
        captcha_solver=False,
    )
    try:
        await browser.start()
        await browser.navigate_to(url)
        await asyncio.sleep(5)
        before = {
            "current_url": _safe_url(await browser.get_current_page_url()),
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
            if not looks_like_challenge_text(state) and not looks_like_challenge_text(title):
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
            "current_url": _safe_url(final["current_url"]),
            "title": final["title"],
        }
        return {
            "ok": True,
            "status": "session_ready" if not challenge_seen or not looks_like_challenge_text(after["title"]) else "challenge_still_present",
            "challenge_seen": challenge_seen,
            "before": before,
            "after": after,
        }
    finally:
        await browser.close()
