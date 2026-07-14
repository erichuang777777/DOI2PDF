from pathlib import Path

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
    }
    monkeypatch.setattr(
        web,
        "_settings",
        lambda: web.Settings(contact_email="a@example.org", setup_complete=True, **secrets),
    )
    pages = web.setup() + web.configure()
    for secret in secrets.values():
        assert secret not in pages
    assert 'name="PUBMED_API_KEY" value=""' in pages
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


def test_job_log_redacts_configured_secrets(monkeypatch):
    monkeypatch.setenv("PUBMED_API_KEY", "do-not-display")
    with web._JOB_LOCK:
        web._JOBS.clear()
    job_id = web._new_job("10.1234/example")
    web._job_event(job_id, {"percent": 50, "stage": "test", "message": "failure do-not-display"})
    payload = json_from_response(web.job_status(job_id))
    assert "do-not-display" not in str(payload)
    assert "[redacted]" in str(payload)


def json_from_response(response):
    import json

    return json.loads(response.body)
