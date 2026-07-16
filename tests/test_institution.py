import json
import time
from pathlib import Path

import pytest

from doi2pdf.config import Settings
from doi2pdf.institution import (
    DailyLimitReached,
    InstitutionalBrowser,
    ProfileBusy,
    enforce_daily_limit,
    institution_daily_count,
    profile_lock,
)
from doi2pdf.publisher_routes import route_for
from tests._pdf import make_pdf


def test_openathens_target_is_percent_encoded():
    browser = InstitutionalBrowser(
        Settings(openathens_redirector_prefix="https://go.openathens.net/redirector/example.edu?url=")
    )
    url, family = browser.access_url("10.1002/test")
    assert family == "openathens"
    assert url.endswith("https%3A%2F%2Fdoi.org%2F10.1002%2Ftest")


def test_off_campus_allows_openathens_but_not_ezproxy():
    openathens = Settings(
        network_mode="off_campus",
        openathens_redirector_prefix="https://go.openathens.net/redirector/example.edu?url=",
    )
    assert openathens.allow_institutional_fallback()
    assert InstitutionalBrowser(openathens)._family() == "openathens"
    ezproxy = Settings(network_mode="off_campus", ezproxy_prefix="https://login.example.edu/login?url=")
    assert not ezproxy.allow_institutional_fallback()
    assert InstitutionalBrowser(ezproxy)._family() is None


def test_campus_mode_supports_direct_publisher_routes_without_proxy():
    browser = InstitutionalBrowser(Settings(network_mode="campus"))
    assert browser._family() == "campus"
    assert browser._route_entry_url("10.1056/NEJMoa1", route_for("10.1056/NEJMoa1")) == "https://www.nejm.org/doi/pdf/10.1056/NEJMoa1"


def test_auto_mode_detects_configured_campus_network(monkeypatch):
    monkeypatch.setattr("doi2pdf.config._local_ip_addresses", lambda: {"140.112.25.8"})
    assert Settings(network_mode="auto", campus_cidrs=("140.112.0.0/16",)).effective_network_mode() == "campus"
    assert Settings(network_mode="auto", campus_cidrs=("10.0.0.0/8",)).effective_network_mode() == "off_campus"


def test_ezproxy_suffix_enables_original_publisher_routes():
    browser = InstitutionalBrowser(Settings(network_mode="campus", ezproxy_suffix="proxy.example.edu"))
    assert browser._route_entry_url("10.1056/NEJMoa1", route_for("10.1056/NEJMoa1")) == "https://www-nejm-org.proxy.example.edu/doi/pdf/10.1056/NEJMoa1"
    meta = route_for("10.3174/ajnr.1")
    assert browser._route_entry_url("10.3174/ajnr.1", meta) == "https://www-ajnr-org.proxy.example.edu/lookup/doi/10.3174/ajnr.1"


def test_profile_lock_is_exclusive_and_recovers_stale_holder(tmp_path: Path):
    with profile_lock(tmp_path):
        with pytest.raises(ProfileBusy):
            with profile_lock(tmp_path):
                pass
    lock = tmp_path / ".doi2pdf.lock"
    lock.write_text(json.dumps({"pid": 99999999, "time": time.time() - 3600}), encoding="utf-8")
    with profile_lock(tmp_path):
        assert lock.exists()
    assert not lock.exists()


def test_daily_limit_counts_fetches_only(tmp_path: Path):
    log = tmp_path / "access_log.jsonl"
    today = time.strftime("%Y-%m-%d", time.localtime())
    log.write_text("\n".join([
        json.dumps({"date": today, "kind": "fetch"}),
        json.dumps({"date": today, "kind": "login"}),
        "not-json",
    ]), encoding="utf-8")
    assert institution_daily_count(log) == 1
    with pytest.raises(DailyLimitReached):
        enforce_daily_limit(log, 1)


def test_rate_settings_cannot_be_disabled(monkeypatch):
    monkeypatch.setenv("DOI2PDF_INSTITUTION_INTERVAL_S", "0")
    monkeypatch.setenv("DOI2PDF_MAX_INSTITUTION_REQUESTS_PER_DAY", "99999")
    settings = Settings.from_env()
    assert settings.min_institution_interval_s == 15
    assert settings.max_institution_requests_per_day == 100


def test_placeholder_email_requires_first_run_setup():
    settings = Settings(contact_email="you@example.org", setup_complete=True)
    assert settings.needs_setup()
    assert "real contact email" in settings.validate()[0]


def test_library_login_must_be_https():
    settings = Settings(contact_email="a@example.org", library_login_url="http://login.example.org")
    assert "LIBRARY_LOGIN_URL must be an absolute https:// URL." in settings.validate()


def test_web_login_mode_is_forwarded_without_terminal_prompt(monkeypatch):
    browser = InstitutionalBrowser(Settings(network_mode="campus", ezproxy_prefix="https://login.example.edu/login?url="))
    recorded = {}

    def browse(url, doi, spec, login_only=False, wait_for_console=True):
        recorded.update({"url": url, "login_only": login_only, "wait_for_console": wait_for_console})

    monkeypatch.setattr(browser, "_browse", browse)
    browser.login(wait_for_console=False)
    assert recorded["login_only"] is True
    assert recorded["wait_for_console"] is False


def test_validated_learned_selector_is_reused_and_promoted(tmp_path):
    class Response:
        status = 200
        url = "https://publisher.example/paper.pdf"

        @staticmethod
        def body():
            return make_pdf()

    class Request:
        @staticmethod
        def get(*args, **kwargs):
            return Response()

    class Context:
        request = Request()

    class Locator:
        @staticmethod
        def count():
            return 1

        @staticmethod
        def get_attribute(name):
            return "/paper.pdf" if name == "href" else None

    class Page:
        url = "https://publisher.example/article"

        @staticmethod
        def wait_for_timeout(value):
            pass

        @staticmethod
        def content():
            return '<html><a href="/paper.pdf">Download PDF</a></html>'

        @staticmethod
        def locator(selector):
            class First:
                first = Locator()
            return First()

    browser = InstitutionalBrowser(Settings(browser_profile=tmp_path))
    browser.rules.remember("publisher.example", "#download", source="llm")
    content, status = browser._generic_or_meta(Page(), Context(), [], "10.1/example", None)
    assert content.startswith(b"%PDF-") and status == "pdf_learned_rule"
    assert browser.rules.list()[0]["status"] == "verified"


def test_cloudflare_challenge_is_reported_explicitly():
    class Page:
        url = "https://www.nejm.org/doi/pdf/10.1056/NEJMoa2600157"

        @staticmethod
        def wait_for_timeout(value):
            pass

        @staticmethod
        def content():
            return "Performing security verification"

        @staticmethod
        def title():
            return "Just a moment..."

    browser = InstitutionalBrowser(Settings())
    content, status = browser._generic_or_meta(Page(), type("Context", (), {"request": None})(), [], "10.1056/NEJMoa2600157", None)
    assert content is None
    assert status == "cf_challenge"


def test_playwright_pdf_body_honors_declared_size_before_reading():
    class Response:
        headers = {"content-length": str(100 * 1024 * 1024 + 1)}

        @staticmethod
        def body():
            raise AssertionError("oversize response body must not be read")

    body, status = InstitutionalBrowser._playwright_body(Response())
    assert body is None
    assert status == "pdf_too_large"


def test_playwright_pdf_body_honors_post_read_limit(monkeypatch):
    class Response:
        headers = {}

        @staticmethod
        def body():
            return b"123456789"

    monkeypatch.setattr("doi2pdf.institution.MAX_PDF_BYTES", 8)
    body, status = InstitutionalBrowser._playwright_body(Response())
    assert body is None
    assert status == "pdf_too_large"


def test_llm_endpoint_requires_https_or_loopback():
    settings = Settings(llm_enabled=True, llm_base_url="http://remote.example/v1", llm_model="ranker")
    assert any("HTTPS or a loopback" in issue for issue in settings.validate())
    embedded = Settings(llm_enabled=True, llm_base_url="https://llm.example/v1?token=secret", llm_model="ranker")
    assert any("cannot contain credentials" in issue for issue in embedded.validate())
