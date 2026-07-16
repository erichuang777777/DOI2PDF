from pathlib import Path
import asyncio
import urllib.parse

from fastapi.responses import RedirectResponse

from doi2pdf import web
from doi2pdf.models import FetchResult


def test_home_has_retrieval_form(monkeypatch):
    monkeypatch.setattr(web, "_settings", lambda: web.Settings(contact_email="doctor@hospital.org", setup_complete=True))
    page = web.home()
    assert "Retrieve a paper" in page
    assert 'name="identifier"' in page
    assert "OpenAthens/EZproxy" in page
    assert "Starting the live tracker" in page
    assert 'href="/activity"' in page


def test_home_discloses_terms_of_service_risk(monkeypatch):
    monkeypatch.setattr(web, "_settings", lambda: web.Settings(contact_email="doctor@hospital.org", setup_complete=True))
    assert "terms of service" in web.home()


def test_configure_discloses_terms_of_service_risk(monkeypatch):
    monkeypatch.setattr(web, "_settings", lambda: web.Settings(contact_email="a@example.org", setup_complete=True))
    assert "terms of service" in web.configure()


def test_first_run_redirects_to_guided_setup(monkeypatch):
    monkeypatch.setattr(web, "_settings", lambda: web.Settings(contact_email="you@example.org"))
    response = web.home()
    assert isinstance(response, RedirectResponse)
    assert response.headers["location"] == "/setup"


def test_setup_explains_required_and_optional_fields(monkeypatch):
    monkeypatch.setattr(web, "_settings", lambda: web.Settings())
    page = web.setup()
    assert "Your contact email (required)" in page
    assert "Library access (optional)" in page
    assert "Never enter your library password" in page
    assert "Official application instructions" in page
    assert "dev.elsevier.com" in page
    assert 'name="DOI2PDF_NETWORK_MODE"' in page


def test_write_env_preserves_secret_when_blank(tmp_path: Path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("PUBMED_API_KEY=keep-me\nUNPAYWALL_EMAIL=old@example.org\n", encoding="utf-8")
    monkeypatch.setattr(web, "ENV_PATH", env)
    monkeypatch.setenv("PUBMED_API_KEY", "old-process-value")
    monkeypatch.setenv("UNPAYWALL_EMAIL", "old@example.org")
    web._write_env({"PUBMED_API_KEY": "", "UNPAYWALL_EMAIL": "new@example.org"})
    content = env.read_text(encoding="utf-8")
    assert "PUBMED_API_KEY=keep-me" in content
    assert "UNPAYWALL_EMAIL=new@example.org" in content
    assert web.os.environ["PUBMED_API_KEY"] == "keep-me"
    assert web.os.environ["UNPAYWALL_EMAIL"] == "new@example.org"


def test_settings_pages_never_render_stored_api_keys(monkeypatch):
    secrets = {
        "pubmed_api_key": "pubmed-secret",
        "semantic_scholar_api_key": "s2-secret",
        "elsevier_api_key": "elsevier-secret",
        "elsevier_insttoken": "elsevier-inst-secret",
        "wiley_tdm_token": "wiley-secret",
        "springer_api_key": "springer-secret",
        "library_password": "library-secret",
        "library_username": "library-user",
        "llm_api_key": "llm-secret",
        "llm_enabled": True,
        "llm_base_url": "https://llm.example/v1",
        "llm_model": "ranker",
    }
    monkeypatch.setattr(
        web,
        "_settings",
        lambda: web.Settings(contact_email="a@example.org", setup_complete=True, **secrets),
    )
    pages = web.setup() + web.configure()
    for key, secret in secrets.items():
        if key.endswith("api_key") or key in {"elsevier_insttoken", "wiley_tdm_token", "library_password", "library_username"}:
            assert secret not in pages
    assert 'name="PUBMED_API_KEY" value=""' in pages
    assert 'name="LIBRARY_PASSWORD" value=""' in pages
    assert 'name="LIBRARY_USERNAME" value=""' in pages
    assert 'name="DOI2PDF_LLM_API_KEY" value=""' in pages
    assert 'name="DOI2PDF_NETWORK_MODE"' in pages
    assert "configured — leave blank to keep" in pages


def test_health_does_not_expose_secrets(monkeypatch):
    monkeypatch.setattr(
        web,
        "_settings",
        lambda: web.Settings(contact_email="a@example.org", pubmed_api_key="top-secret", setup_complete=True),
    )
    payload = json_from_response(web.health())
    assert "top-secret" not in str(payload)
    assert payload["version"]
    assert payload["network_mode"] == "auto"


def test_registered_pdf_can_be_served_inline_or_downloaded(tmp_path: Path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    token = web._register_file(pdf)
    inline = web.serve_file(token)
    download = web.serve_file(token, download=True)
    assert Path(inline.path) == pdf.resolve()
    assert inline.headers["content-disposition"].startswith("inline")
    assert download.headers["content-disposition"].startswith("attachment")


def test_background_job_tracks_progress_and_result(tmp_path: Path, monkeypatch):
    class FakeClient:
        def fetch(self, identifier, output, use_institution, progress):
            progress({"percent": 20, "stage": "open_access", "message": "Checking indexes", "source": "unpaywall"})
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"%PDF-1.4\n")
            progress({"percent": 100, "stage": "complete", "message": "Saved", "status": "pdf_saved"})
            return FetchResult(
                doi="10.1234/example", ok=True, path=output, route="unpaywall",
                layer="open_access", bytes=9, sha256="abc",
            )

    monkeypatch.setattr(web, "DOI2PDF", lambda settings: FakeClient())
    monkeypatch.setattr(web, "_settings", lambda: web.Settings(contact_email="a@example.org", setup_complete=True))
    with web._JOB_LOCK:
        web._JOBS.clear()
    job_id = web._new_job("10.1234/example")
    web._run_fetch_job(job_id, {"identifier": "10.1234/example", "output_dir": str(tmp_path)})
    payload = json_from_response(web.job_status(job_id))
    assert payload["state"] == "succeeded"
    assert payload["percent"] == 100
    assert payload["result"]["filename"].endswith(".pdf")
    assert "path" not in payload["result"]
    assert "Checking indexes" in str(payload["events"])
    assert "Open PDF" in web.job_result(job_id)


def test_activity_and_progress_pages_are_live_console_views():
    with web._JOB_LOCK:
        web._JOBS.clear()
    job_id = web._new_job("10.1234/example")
    assert "Activity monitor" in web.activity()
    assert "Recent route events" in web.activity()
    page = web.job_progress(job_id)
    assert "Retrieval progress" in page
    assert f"/api/jobs/${{jobId}}" in page


def test_acceptance_page_offers_only_one_at_a_time_tests(monkeypatch):
    monkeypatch.setattr(web, "_settings", lambda: web.Settings(download_dir=Path("papers")))
    page = web.acceptance()
    assert page.count("Try with my access") == 8
    assert 'name="use_institution" value="1"' in page
    assert "bulk test" in page
    assert "10.1056/NEJMoa2404512" in page


def test_api_check_page_never_displays_key(monkeypatch):
    monkeypatch.setattr(web, "_settings", lambda: web.Settings(pubmed_api_key="top-secret"))
    monkeypatch.setattr(
        web,
        "probe_all",
        lambda settings: [{"provider": "pubmed", "configured": True, "ok": True, "status": "key_accepted", "http_status": 200}],
    )
    page = asyncio.run(web.api_check())
    assert "key_accepted" in page
    assert "top-secret" not in page


def test_routes_page_contains_full_registry_and_sanitized_health(monkeypatch, tmp_path):
    monkeypatch.setattr(web, "_settings", lambda: web.Settings(browser_profile=tmp_path, library_password="secret"))
    page = web.routes_page()
    assert page.count("<code>10.") == 23
    assert "lww_ovid" in page
    assert "secret" not in page


def test_learned_rules_page_is_sanitized_and_forgettable(monkeypatch, tmp_path):
    monkeypatch.setattr(web, "_settings", lambda: web.Settings(browser_profile=tmp_path))
    web.RuleStore(tmp_path / "learned_pdf_rules.json").remember("publisher.example", "a.download", text_hint="Download PDF", source="llm")
    page = web.learned_rules_page()
    assert "publisher.example" in page and "a.download" in page
    assert "token=secret" not in page.lower()
    assert 'action="/rules/forget"' in page


def test_configure_has_official_api_links_and_library_assistant(monkeypatch):
    monkeypatch.setattr(web, "_settings", lambda: web.Settings(contact_email="a@example.org", setup_complete=True))
    page = web.configure()
    for host in ("ncbi.nlm.nih.gov", "semanticscholar.org", "dev.elsevier.com", "onlinelibrary.wiley.com", "dev.springernature.com"):
        assert host in page
    assert 'action="/library-detect"' in page
    assert "Nothing is saved until" in page
    assert 'name="DOI2PDF_NETWORK_MODE"' in page


def test_library_detect_preview_never_renders_target_url():
    class Request:
        async def body(self):
            value = "https://go.openathens.net/redirector/example.edu?url=https%3A%2F%2Fpublisher.example%2Fpaper%3Ftoken%3Dsecret"
            return urllib.parse.urlencode({"library_url": value}).encode()

    page = asyncio.run(web.library_detect(Request()))
    assert "OPENATHENS_REDIRECTOR_PREFIX" in page
    assert "publisher.example" not in page
    assert "token" not in page


def test_apply_detected_library_setting_writes_only_reviewed_prefix(tmp_path, monkeypatch):
    class Request:
        async def body(self):
            return urllib.parse.urlencode({
                "field": "EZPROXY_PREFIX",
                "value": "https://login.example.edu/login?url=",
                "start_login": "0",
            }).encode()

    env = tmp_path / ".env"
    monkeypatch.setattr(web, "ENV_PATH", env)
    response = asyncio.run(web.apply_library_detection(Request()))
    assert isinstance(response, RedirectResponse)
    text = env.read_text(encoding="utf-8")
    assert "EZPROXY_PREFIX=https://login.example.edu/login?url=" in text
    assert "publisher" not in text


def test_job_log_redacts_configured_secrets(monkeypatch):
    monkeypatch.setenv("PUBMED_API_KEY", "do-not-display")
    with web._JOB_LOCK:
        web._JOBS.clear()
    job_id = web._new_job("10.1234/example")
    web._job_event(job_id, {"percent": 50, "stage": "test", "message": "failure do-not-display"})
    payload = json_from_response(web.job_status(job_id))
    assert "do-not-display" not in str(payload)
    assert "[redacted]" in str(payload)


class _Headers(dict):
    """Case-insensitive header lookup like Starlette's Headers."""

    def get(self, key, default=None):
        return super().get(key.lower(), default)


def test_origin_guard_allows_loopback_get():
    headers = _Headers({"host": "127.0.0.1:8765"})
    assert web._origin_guard("GET", headers) is None


def test_origin_guard_rejects_foreign_host_for_dns_rebinding():
    headers = _Headers({"host": "evil.example.com"})
    assert web._origin_guard("GET", headers) == "host_not_allowed"


def test_origin_guard_allows_same_origin_post():
    headers = _Headers({"host": "127.0.0.1:8765", "origin": "http://127.0.0.1:8765"})
    assert web._origin_guard("POST", headers) is None


def test_origin_guard_rejects_cross_site_post():
    headers = _Headers({"host": "127.0.0.1:8765", "origin": "http://evil.example.com"})
    assert web._origin_guard("POST", headers) == "cross_origin"


def test_origin_guard_rejects_post_without_origin_or_referer():
    headers = _Headers({"host": "127.0.0.1:8765"})
    assert web._origin_guard("POST", headers) == "missing_origin"


def test_origin_guard_accepts_referer_fallback():
    headers = _Headers({"host": "localhost:8765", "referer": "http://localhost:8765/configure"})
    assert web._origin_guard("POST", headers) is None


def test_resolve_output_dir_allows_subfolder_of_root(tmp_path):
    settings = web.Settings(download_dir=tmp_path)
    resolved = web._resolve_output_dir(str(tmp_path / "sub"), settings)
    assert resolved == (tmp_path / "sub").resolve()


def test_resolve_output_dir_blocks_parent_traversal(tmp_path):
    settings = web.Settings(download_dir=tmp_path / "downloads")
    import pytest

    with pytest.raises(ValueError):
        web._resolve_output_dir(str(tmp_path / "downloads" / ".." / ".." / "evil"), settings)


def test_resolve_output_dir_blocks_absolute_escape(tmp_path):
    settings = web.Settings(download_dir=tmp_path / "downloads")
    import pytest

    with pytest.raises(ValueError):
        web._resolve_output_dir("/tmp/attacker", settings)


def test_resolve_output_dir_defaults_to_configured_root(tmp_path):
    settings = web.Settings(download_dir=tmp_path)
    assert web._resolve_output_dir("", settings) == tmp_path.resolve()


def json_from_response(response):
    import json

    return json.loads(response.body)
