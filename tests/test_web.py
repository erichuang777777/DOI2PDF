from pathlib import Path

from doi2pdf import web


def test_home_has_retrieval_form():
    page = web.home()
    assert "Retrieve a paper" in page
    assert 'name="identifier"' in page
    assert "OpenAthens/EZproxy" in page


def test_write_env_preserves_secret_when_blank(tmp_path: Path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("PUBMED_API_KEY=keep-me\nUNPAYWALL_EMAIL=old@example.org\n", encoding="utf-8")
    monkeypatch.setattr(web, "ENV_PATH", env)
    web._write_env({"PUBMED_API_KEY": "", "UNPAYWALL_EMAIL": "new@example.org"})
    content = env.read_text(encoding="utf-8")
    assert "PUBMED_API_KEY=keep-me" in content
    assert "UNPAYWALL_EMAIL=new@example.org" in content


def test_health_does_not_expose_secrets(monkeypatch):
    monkeypatch.setattr(
        web,
        "_settings",
        lambda: web.Settings(contact_email="a@example.org", pubmed_api_key="top-secret"),
    )
    payload = json_from_response(web.health())
    assert "top-secret" not in str(payload)
    assert payload["version"]


def json_from_response(response):
    import json

    return json.loads(response.body)
