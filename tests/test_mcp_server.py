import asyncio
from pathlib import Path

from doi2pdf import mcp_server
from doi2pdf.config import Settings
from doi2pdf.models import FetchResult


def run(coro):
    return asyncio.run(coro)


def test_resolve_identifier_reports_invalid_identifier(monkeypatch):
    class InvalidIdentifiers:
        @staticmethod
        def resolve(value):
            raise ValueError("Could not resolve a trustworthy DOI")

    class FakeApp:
        def __init__(self, settings):
            self.identifiers = InvalidIdentifiers()

    monkeypatch.setattr(mcp_server, "DOI2PDF", FakeApp)
    result = run(mcp_server.resolve_identifier("not-a-doi"))
    assert result == {"ok": False, "status": "invalid_identifier", "error": "Could not resolve a trustworthy DOI"}


def test_resolve_identifier_normalizes_a_valid_doi(monkeypatch):
    monkeypatch.setattr(mcp_server, "_settings", lambda: Settings())
    result = run(mcp_server.resolve_identifier("10.1038/nphys1170"))
    assert result == {"ok": True, "status": "resolved", "doi": "10.1038/nphys1170"}


def test_check_setup_reports_ready_when_configured(monkeypatch):
    monkeypatch.setattr(
        mcp_server.Settings,
        "from_env",
        lambda: Settings(
            contact_email="agent@example.org",
            unpaywall_email="agent@example.org",
            network_mode="campus",
            openathens_redirector_prefix="https://go.openathens.net/redirector/example?url=",
            setup_complete=True,
        ),
    )
    result = run(mcp_server.check_setup())
    assert result["ok"] is True
    assert result["status"] == "ready"
    assert result["routes"]["institution"] is True


def test_check_setup_reports_setup_required(monkeypatch):
    monkeypatch.setattr(
        mcp_server.Settings,
        "from_env",
        lambda: Settings(contact_email="agent@example.org", unpaywall_email="agent@example.org", setup_complete=False),
    )
    result = run(mcp_server.check_setup())
    assert result["ok"] is False
    assert result["status"] == "setup_required"


def test_fetch_pdf_names_the_file_from_zotero_metadata(tmp_path, monkeypatch):
    class FakeIdentifiers:
        @staticmethod
        def resolve(value):
            return "10.1234/example"

    class FakeApp:
        def __init__(self, settings):
            self.identifiers = FakeIdentifiers()

        def fetch(self, doi, output, use_institution=True):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"%PDF-1.4\n")
            return FetchResult(doi=doi, ok=True, path=output, route="unpaywall", layer="open_access", bytes=9, sha256="abc")

    monkeypatch.setattr(mcp_server, "DOI2PDF", FakeApp)
    monkeypatch.setattr(mcp_server, "_settings", lambda: Settings(download_dir=tmp_path))
    result = run(
        mcp_server.fetch_pdf(
            "10.1234/example", output_dir=str(tmp_path), zotero_key="9ET75JMH", author="Vaswani", year="2017"
        )
    )
    assert result["ok"] is True
    assert result["status"] == "pdf_saved"
    assert Path(result["path"]).name == "9ET75JMH_Vaswani_2017.pdf"
    assert Path(result["path"]).exists()


def test_fetch_pdf_reports_resolver_url_when_no_route_succeeds(tmp_path, monkeypatch):
    class FakeIdentifiers:
        @staticmethod
        def resolve(value):
            return "10.1234/example"

    class FakeApp:
        def __init__(self, settings):
            self.identifiers = FakeIdentifiers()

        def fetch(self, doi, output, use_institution=True):
            return FetchResult(doi=doi, ok=False, resolver_url="https://resolver.example/10.1234/example")

    monkeypatch.setattr(mcp_server, "DOI2PDF", FakeApp)
    monkeypatch.setattr(mcp_server, "_settings", lambda: Settings(download_dir=tmp_path))
    result = run(mcp_server.fetch_pdf("10.1234/example", output_dir=str(tmp_path)))
    assert result["ok"] is False
    assert result["status"] == "manual_required"
    assert result["resolver_url"] == "https://resolver.example/10.1234/example"


def test_list_publisher_routes_returns_the_full_registry(monkeypatch, tmp_path):
    monkeypatch.setattr(mcp_server, "_settings", lambda: Settings(browser_profile=tmp_path))
    result = run(mcp_server.list_publisher_routes())
    assert result["ok"] is True
    assert len(result["registry"]) == len(mcp_server.ROUTES)


def test_check_holdings_reports_not_configured_without_holdings_db(monkeypatch):
    monkeypatch.setattr(mcp_server, "_settings", lambda: Settings())
    result = run(mcp_server.check_holdings("10.1234/example"))
    assert result == {"ok": False, "status": "not_configured", "error": "Set HOLDINGS_DB to a readable SQLite database."}


def test_check_api_keys_reports_no_keys_configured(monkeypatch):
    monkeypatch.setattr(mcp_server, "_settings", lambda: Settings())
    result = run(mcp_server.check_api_keys())
    assert result["status"] == "no_keys_configured"


def test_all_tools_are_registered_with_descriptions():
    tools = run(mcp_server.mcp.list_tools())
    names = {tool.name for tool in tools}
    assert names == {
        "resolve_identifier",
        "check_setup",
        "list_publisher_routes",
        "check_holdings",
        "check_api_keys",
        "fetch_pdf",
    }
    assert all(tool.description for tool in tools)
