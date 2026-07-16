from pathlib import Path
import tomllib

import yaml

from doi2pdf.browser_assist import _safe_url
from doi2pdf import __version__
from doi2pdf.config import Settings
from doi2pdf.models import Attempt, FetchResult


def test_skill_metadata_and_agent_prompt_are_valid():
    skill_path = Path("skills/doi2pdf/SKILL.md")
    text = skill_path.read_text(encoding="utf-8")
    _, frontmatter, _ = text.split("---", 2)
    metadata = yaml.safe_load(frontmatter)
    assert metadata["name"] == "doi2pdf"
    assert set(metadata) == {"name", "description"}

    agent = yaml.safe_load(Path("skills/doi2pdf/agents/openai.yaml").read_text(encoding="utf-8"))
    assert 25 <= len(agent["interface"]["short_description"]) <= 64
    assert "$doi2pdf" in agent["interface"]["default_prompt"]


def test_package_and_runtime_versions_match():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == __version__


def test_windows_default_setup_is_lightweight_and_browser_is_explicit():
    launcher = Path("DOI2PDF.bat").read_text(encoding="utf-8")
    browser_setup = Path("DOI2PDF-browser-setup.bat").read_text(encoding="utf-8")
    assert 'pip install -e ".[web]"' in launcher
    assert "playwright install chromium" not in launcher
    assert 'pip install -e ".[browser]"' in browser_setup
    assert "playwright install chromium" in browser_setup


def test_http_user_agent_uses_release_version():
    from doi2pdf.http import HttpClient

    assert HttpClient("user@example.org").session.headers["User-Agent"].startswith(f"DOI2PDF/{__version__}")


def test_machine_result_redacts_candidate_urls_and_attachment_metadata(tmp_path):
    result = FetchResult(
        doi="10.1234/example",
        metadata={
            "zotero": {
                "title": "Example",
                "date": "2026",
                "attachments": [{"url": "https://publisher.example/file?token=secret"}],
            }
        },
        attempts=[
            Attempt(
                "translator",
                "institution",
                "https://publisher.example/file?token=secret",
                "failed",
                "request failed at https://publisher.example/file?token=secret",
            )
        ],
        path=tmp_path / "paper.pdf",
    )
    payload = result.to_dict()
    rendered = str(payload)
    assert "token=secret" not in rendered
    assert "attachments" not in payload["metadata"]["zotero"]
    assert payload["attempts"][0]["url"] is None
    assert "[redacted-url]" in payload["attempts"][0]["detail"]


def test_browser_assist_diagnostic_url_drops_credentials_query_and_fragment():
    assert _safe_url("https://user:pass@example.org/paper.pdf?token=secret#page=2") == "https://example.org/paper.pdf"


def test_resolver_replaces_only_doi_placeholder():
    settings = Settings(resolver_template="https://resolver.example/openurl?ctx={ctx}&doi={doi}")
    assert settings.resolver_url("10.1/example") == "https://resolver.example/openurl?ctx={ctx}&doi=10.1/example"
