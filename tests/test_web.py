from pathlib import Path

from fastapi.responses import RedirectResponse

from doi2pdf import web


def test_home_has_retrieval_form(monkeypatch):
    monkeypatch.setattr(web, "_settings", lambda: web.Settings(contact_email="doctor@hospital.org", setup_complete=True))
    page = web.home()
    assert "Retrieve a paper" in page
    assert 'name="identifier"' in page
    assert "OpenAthens/EZproxy" in page
    assert "Searching for a verified PDF" in page


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


def json_from_response(response):
    import json

    return json.loads(response.body)
