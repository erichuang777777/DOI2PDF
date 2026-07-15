from __future__ import annotations

import json
import os
import time
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

from .config import Settings
from .holdings import Holdings
from .http import looks_like_pdf
from .publisher_routes import (
    RouteSpec, citation_pdf_url, lww_article_details, lww_signed_pdf_url,
    ovid_viewer_pdf_url, proxy_host, rewrite_for_proxy, route_for, template_url,
)


class ProfileBusy(RuntimeError):
    pass


class DailyLimitReached(RuntimeError):
    pass


@dataclass
class InstitutionResult:
    content: bytes | None
    route: str
    status: str
    entitlement: dict = field(default_factory=dict)


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
    E3_MARKERS = ("License Service Failure", "Code: E3", "LicenseServiceFailure")

    def __init__(self, settings: Settings):
        self.settings = settings
        self.holdings = Holdings(settings)

    @property
    def log_path(self) -> Path:
        return self.settings.browser_profile / "access_log.jsonl"

    def _family(self) -> str | None:
        if self.settings.openathens_redirector_prefix:
            return "openathens"
        if self.settings.ezproxy_suffix or self.settings.ezproxy_prefix:
            return "ezproxy"
        return None

    def authorize_url(self, target: str, doi: str = "") -> str | None:
        if self.settings.openathens_redirector_prefix:
            return self.settings.openathens_redirector_prefix + quote(target, safe="")
        if self.settings.ezproxy_suffix:
            return rewrite_for_proxy(target, self.settings.ezproxy_suffix)
        if self.settings.ezproxy_prefix:
            prefix = self.settings.ezproxy_prefix
            if "{url}" in prefix or "{doi}" in prefix:
                return prefix.format(url=quote(target, safe=""), doi=quote(doi, safe=""))
            return prefix + quote(target, safe="")
        return None

    def access_url(self, doi: str) -> tuple[str | None, str | None]:
        return self.authorize_url(f"https://doi.org/{doi}", doi), self._family()

    def login(self) -> None:
        url = self.settings.library_login_url
        if not url:
            url, _ = self.access_url("10.5555/doi2pdf-login-check")
        if not url:
            raise ValueError("Configure OPENATHENS_REDIRECTOR_PREFIX, EZPROXY_PREFIX, or EZPROXY_SUFFIX first")
        self._browse(url, None, None, login_only=True)

    def fetch(self, doi: str) -> InstitutionResult:
        family = self._family()
        if not family:
            return InstitutionResult(None, "not_configured", "not_configured")
        entitlement = self.holdings.check(doi)
        spec = route_for(doi)
        target = self._route_entry_url(doi, spec)
        if not target:
            return InstitutionResult(None, f"{family}:no_route", "no_route", entitlement)
        content, status = self._browse(target, doi, spec)
        route = f"{family}:{spec.label if spec else 'generic'}:{spec.kind if spec else 'generic'}"
        self._log_route(doi, route, status, entitlement)
        return InstitutionResult(content, route, status, entitlement)

    def _route_entry_url(self, doi: str, spec: RouteSpec | None) -> str | None:
        if spec and spec.kind == "tpl":
            return self.authorize_url(template_url(spec, doi), doi)
        if self.settings.ezproxy_suffix:
            if spec and spec.kind == "meta" and spec.host:
                return f"https://{proxy_host(spec.host, self.settings.ezproxy_suffix)}/lookup/doi/{doi}"
            return f"https://doi-org.{self.settings.ezproxy_suffix.lstrip('.')}/{doi}"
        return self.authorize_url(f"https://doi.org/{doi}", doi)

    def _log(self, event: dict) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        safe = {key: value for key, value in event.items() if key not in {"url", "headers", "cookies"}}
        safe.update({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()), "date": time.strftime("%Y-%m-%d", time.localtime())})
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(safe, ensure_ascii=False) + "\n")

    def _log_route(self, doi: str, route: str, status: str, entitlement: dict) -> None:
        self._log({
            "kind": "route", "doi": doi, "prefix": doi.split("/", 1)[0], "route": route,
            "status": status, "subscribed": entitlement.get("subscribed"),
            "covered": entitlement.get("covered"), "platform": entitlement.get("platform"),
        })

    def _throttle(self) -> None:
        marker = self.settings.browser_profile / ".last_request"
        if marker.exists():
            delay = self.settings.min_institution_interval_s - (time.time() - marker.stat().st_mtime)
            if delay > 0:
                time.sleep(delay)
        marker.touch()

    @staticmethod
    def _response_status(response, body: bytes) -> str:
        if looks_like_pdf(body):
            return "pdf"
        head = body[:4000].lower()
        if response.status == 429 or b"too many requests" in head or b"rate limit" in head:
            return "rate_limited"
        if b"just a moment" in head or b"attention required" in head:
            return "cf_challenge"
        if b"you have been blocked" in head or response.status == 1020:
            return "cf_block"
        if b"host does not match" in head or b"oh noes" in head:
            return "proxy_host_unregistered"
        if "/login" in (response.url or ""):
            return "auth_required"
        return f"http_{response.status}"

    def _request_pdf(self, context, url: str, referer: str | None = None, retries: int = 1) -> tuple[bytes | None, str]:
        for attempt in range(retries):
            response = context.request.get(
                url, headers={"Referer": referer} if referer else {},
                timeout=max(5_000, self.settings.request_timeout_s * 1000),
            )
            body = response.body()
            status = self._response_status(response, body)
            if status == "pdf":
                return body, status
            if response.status != 503 or attempt + 1 >= retries:
                return None, status
            time.sleep(3)
        return None, "not_pdf"

    def _generic_or_meta(self, page, context, captured: list[bytes], doi: str, spec: RouteSpec | None) -> tuple[bytes | None, str]:
        page.wait_for_timeout(4_000)
        if captured:
            return captured[0], "pdf"
        document = page.content()
        pdf_url = citation_pdf_url(document)
        if not pdf_url:
            links = page.locator('a[href$=".pdf"],a[href*="/pdf/"],a[href*="/pdfdirect/"],a:has-text("Download PDF"),a:has-text("View PDF")')
            ranked: list[tuple[int, str]] = []
            for index in range(min(links.count(), 20)):
                link = links.nth(index)
                href = link.get_attribute("href")
                if href:
                    low = href.lower()
                    if not any(term in low for term in ("supplement", "citation", "metrics")):
                        ranked.append(((5 if re.search(r"\.pdf(?:$|[?#])", low) else 0) + (3 if "pdf" in (link.inner_text() or "").lower() else 0), urljoin(page.url, href)))
            pdf_url = max(ranked)[1] if ranked else None
        if not pdf_url:
            return None, "no_citation_pdf_url" if spec and spec.kind == "meta" else "no_pdf_link"
        if self.settings.ezproxy_suffix:
            pdf_url = rewrite_for_proxy(pdf_url, self.settings.ezproxy_suffix)
        return self._request_pdf(context, pdf_url, page.url)

    def _lww(self, page, context, captured: list[bytes], doi: str) -> tuple[bytes | None, str]:
        page.wait_for_timeout(4_000)
        if captured:
            return captured[0], "pdf"
        document = page.content()
        if any(marker in document for marker in self.E3_MARKERS):
            self._set_ovid_cooldown()
            return None, "license_seat_e3"
        number, journal = lww_article_details(document, page.url)
        if not number:
            return None, "lww_article_number_missing"
        if "www-ovid" in page.url:
            target = self._sfx_lww_target(context, doi)
            if not target:
                return None, "ovid_sfx_target_missing"
            page.goto(target, wait_until="domcontentloaded", timeout=90_000)
            page.wait_for_timeout(4_000)
            match = re.search(r"/article/(\d{8}-\d{9}-\d{5})/", page.url)
            return self._ovid(page, context, captured, doi, match.group(1) if match else number)
        if not journal:
            return None, "lww_journal_missing"
        origin = f"{urlsplit(page.url).scheme}://{urlsplit(page.url).netloc}"
        viewer = f"{origin}/{journal}/_layouts/15/oaks.journals/downloadpdf.aspx?trckng_src_pg=ArticleViewer&an={number}"
        response = context.request.get(viewer, headers={"Referer": page.url}, timeout=90_000)
        signed = lww_signed_pdf_url(response.text())
        if signed:
            return self._request_pdf(context, signed, viewer, retries=6)
        return self._ovid(page, context, captured, doi, number)

    def _ovid_cooldown_left(self) -> int:
        path = self.settings.browser_profile / ".ovid_e3_until"
        try:
            return max(0, int(float(path.read_text(encoding="utf-8")) - time.time()))
        except (OSError, ValueError):
            return 0

    def _set_ovid_cooldown(self) -> None:
        path = self.settings.browser_profile / ".ovid_e3_until"
        path.write_text(str(time.time() + 1800), encoding="utf-8")

    def _ovid(self, page, context, captured: list[bytes], doi: str, number: str) -> tuple[bytes | None, str]:
        if self._ovid_cooldown_left():
            return None, "ovid_e3_cooldown"
        target = self.authorize_url(f"https://oce.ovid.com/article/{number}/HTML", doi)
        if not target:
            return None, "not_configured"
        network: dict[str, str | None] = {"viewer": None}

        def inspect(response):
            if "/pdfviewer/" in response.url and "file=" in response.url:
                network["viewer"] = response.url

        page.on("response", inspect)
        try:
            page.goto(target, wait_until="domcontentloaded", timeout=90_000)
            for _ in range(30):
                page.wait_for_timeout(1_000)
                if captured or network["viewer"]:
                    break
                document = page.content()
                if any(marker in document for marker in self.E3_MARKERS):
                    self._set_ovid_cooldown()
                    return None, "license_seat_e3"
            if captured:
                return captured[0], "pdf"
            pdf_url = ovid_viewer_pdf_url(network["viewer"], page.content())
            if not pdf_url:
                return None, "ovid_pdf_url_missing"
            content, status = self._request_pdf(context, pdf_url, network["viewer"] or page.url, retries=2)
            return content, status
        finally:
            try:
                page.remove_listener("response", inspect)
                page.goto("about:blank", wait_until="domcontentloaded", timeout=10_000)
            except Exception:
                pass

    def _sfx_lww_target(self, context, doi: str) -> str | None:
        if not self.settings.resolver_template:
            return None
        separator = "&" if "?" in self.settings.resolver_url(doi) else "?"
        response = context.request.get(self.settings.resolver_url(doi) + separator + "sfx.response_type=multi_obj_detailed_xml", timeout=90_000)
        document = response.text()
        for target in re.findall(r"<target>(.*?)</target>", document, re.S):
            if re.search(r"<service_type>\s*getFullTxt\s*</service_type>", target) and "LWW" in target:
                match = re.search(r"<target_url>([^<]+)", target)
                if match:
                    return match.group(1).replace("&amp;", "&")
        return None

    def _browse(self, url: str, doi: str | None, spec: RouteSpec | None, login_only: bool = False):
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Install the browser extra and run: playwright install chromium") from exc

        with profile_lock(self.settings.browser_profile):
            if not login_only:
                enforce_daily_limit(self.log_path, self.settings.max_institution_requests_per_day)
            self._throttle()
            self._log({"kind": "login" if login_only else "fetch", "doi": doi})
            with sync_playwright() as pw:
                # Login, SSO and MFA must always be visible to the user. Publisher
                # routes known to block unattended Chromium are also forced visible.
                headless = False if login_only or (spec and spec.headful) else self.settings.browser_headless
                context = pw.chromium.launch_persistent_context(str(self.settings.browser_profile), headless=headless, accept_downloads=True)
                page = context.pages[0] if context.pages else context.new_page()
                captured: list[bytes] = []

                def inspect(response):
                    if "pdf" in (response.headers.get("content-type") or "").lower():
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
                        if self.settings.library_username and self.settings.library_password:
                            user = page.locator(self.settings.library_user_selector).first
                            password = page.locator(self.settings.library_password_selector).first
                            submit = page.locator(self.settings.library_submit_selector).first
                            if user.count() and password.count() and submit.count():
                                user.fill(self.settings.library_username)
                                password.fill(self.settings.library_password)
                                submit.click()
                                page.wait_for_timeout(4_000)
                                if "/login" not in page.url.lower() and password.count() == 0:
                                    return None
                        if not headless:
                            input("Complete institutional login/SSO/MFA in Chromium, then press Enter here... ")
                        return None
                    if spec and spec.kind == "lww":
                        return self._lww(page, context, captured, doi or "")
                    return self._generic_or_meta(page, context, captured, doi or "", spec)
                except PlaywrightTimeoutError:
                    return None, "timeout"
                finally:
                    context.close()
