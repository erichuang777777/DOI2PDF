from __future__ import annotations

import json
import os
import time
import re
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote
from urllib.parse import urljoin

from .config import Settings
from .http import looks_like_pdf


class ProfileBusy(RuntimeError):
    pass


class DailyLimitReached(RuntimeError):
    pass


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def institution_daily_count(log: Path, date: str | None = None) -> int:
    date = date or time.strftime("%Y-%m-%d", time.localtime())
    count = 0
    if not log.exists():
        return 0
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
            count += int(event.get("date") == date and event.get("kind") == "fetch")
        except (ValueError, TypeError):
            continue
    return count


def enforce_daily_limit(log: Path, maximum: int) -> None:
    count = institution_daily_count(log)
    if count >= maximum:
        raise DailyLimitReached(f"Daily institutional request ceiling reached ({count}/{maximum})")


@contextmanager
def profile_lock(profile: Path):
    profile.mkdir(parents=True, exist_ok=True)
    lock = profile / ".doi2pdf.lock"
    try:
        handle = lock.open("x", encoding="utf-8")
        handle.write(json.dumps({"pid": os.getpid(), "time": time.time()}))
        handle.close()
    except FileExistsError as exc:
        try:
            holder = json.loads(lock.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            holder = {}
        stale = time.time() - float(holder.get("time", 0)) > 1800 and not _pid_alive(int(holder.get("pid", 0)))
        if stale:
            lock.unlink(missing_ok=True)
            with profile_lock(profile):
                yield
            return
        raise ProfileBusy(f"Institutional browser profile is busy: {profile}") from exc
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


class InstitutionalBrowser:
    def __init__(self, settings: Settings):
        self.settings = settings

    def access_url(self, doi: str) -> tuple[str | None, str | None]:
        target = f"https://doi.org/{doi}"
        if self.settings.openathens_redirector_prefix:
            return self.settings.openathens_redirector_prefix + quote(target, safe=""), "openathens"
        if self.settings.ezproxy_prefix:
            prefix = self.settings.ezproxy_prefix
            if "{url}" in prefix:
                return prefix.format(url=quote(target, safe=""), doi=quote(doi, safe="")), "ezproxy"
            return prefix + quote(target, safe=""), "ezproxy"
        return None, None

    def login(self) -> None:
        url, _ = self.access_url("10.5555/doi2pdf-login-check")
        if not url:
            raise ValueError("Configure OPENATHENS_REDIRECTOR_PREFIX or EZPROXY_PREFIX first")
        self._browse(url, None, login_only=True)

    def fetch(self, doi: str) -> tuple[bytes | None, str]:
        url, family = self.access_url(doi)
        if not url or not family:
            return None, "not_configured"
        return self._browse(url, doi), family

    def _browse(self, url: str, doi: str | None, login_only: bool = False):
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Install the browser extra and run: playwright install chromium") from exc

        with profile_lock(self.settings.browser_profile):
            log = self.settings.browser_profile / "access_log.jsonl"
            if not login_only:
                enforce_daily_limit(log, self.settings.max_institution_requests_per_day)
            marker = self.settings.browser_profile / ".last_request"
            if marker.exists():
                delay = self.settings.min_institution_interval_s - (time.time() - marker.stat().st_mtime)
                if delay > 0:
                    time.sleep(delay)
            marker.touch()
            with log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
                    "date": time.strftime("%Y-%m-%d", time.localtime()),
                    "kind": "login" if login_only else "fetch",
                    "doi": doi,
                }) + "\n")
            with sync_playwright() as pw:
                context = pw.chromium.launch_persistent_context(
                    str(self.settings.browser_profile), headless=self.settings.browser_headless,
                    accept_downloads=True,
                )
                page = context.pages[0] if context.pages else context.new_page()
                captured: list[bytes] = []

                def inspect(response):
                    if "pdf" not in (response.headers.get("content-type") or "").lower():
                        return
                    try:
                        body = response.body()
                        if looks_like_pdf(body):
                            captured.append(body)
                    except Exception:
                        pass

                page.on("response", inspect)
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=90_000)
                    if login_only:
                        if not self.settings.browser_headless:
                            input("Complete institutional login in Chromium, then press Enter here... ")
                        return None
                    page.wait_for_timeout(4_000)
                    if captured:
                        return captured[0]
                    meta = page.locator('meta[name="citation_pdf_url"]')
                    pdf_url = meta.first.get_attribute("content") if meta.count() else None
                    if not pdf_url:
                        # Follow at most one high-confidence link to avoid multiplying
                        # publisher requests. This covers the legacy site-translator
                        # patterns without embedding publisher-specific bypass logic.
                        links = page.locator(
                            'a[href$=".pdf"], a[href*="/pdf/"], a[href*="/pdfdirect/"], '
                            'a:has-text("Download PDF"), a:has-text("View PDF")'
                        )
                        ranked: list[tuple[int, str]] = []
                        for index in range(min(links.count(), 20)):
                            link = links.nth(index)
                            href = link.get_attribute("href")
                            if not href:
                                continue
                            text = (link.inner_text() or "").lower()
                            low = href.lower()
                            if any(term in low for term in ("supplement", "citation", "metrics")):
                                continue
                            score = (5 if re.search(r"\.pdf(?:$|[?#])", low) else 0) + (3 if "pdf" in text else 0)
                            ranked.append((score, urljoin(page.url, href)))
                        if ranked:
                            pdf_url = max(ranked)[1]
                    if pdf_url:
                        response = context.request.get(pdf_url, headers={"Referer": page.url}, timeout=90_000)
                        body = response.body()
                        if response.ok and looks_like_pdf(body):
                            return body
                    return None
                except PlaywrightTimeoutError:
                    return None
                finally:
                    context.close()
