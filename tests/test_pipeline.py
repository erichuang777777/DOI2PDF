from pathlib import Path

from doi2pdf.config import Settings
from doi2pdf.http import PDF_MAGIC
from doi2pdf.models import Candidate
from doi2pdf.pipeline import DOI2PDF
from doi2pdf.institution import InstitutionResult


PDF = PDF_MAGIC + b" test\n" + b"0" * 2048


class FakeHttp:
    session = None

    def fetch_pdf(self, url, referer=None):
        return (PDF, "pdf") if url.endswith("good.pdf") else (None, "not_pdf")

    def landing_pdf_url(self, url):
        return None, "no_citation_pdf_url"


def test_pipeline_stops_at_verified_oa_candidate(tmp_path: Path):
    app = DOI2PDF(Settings(translator_enabled=False), http=FakeHttp())
    app.oa.candidates = lambda doi: ([
        Candidate("https://example.org/not-html", "unpaywall", "open_access"),
        Candidate("https://example.org/good.pdf", "openalex", "open_access"),
    ], [])
    app.tdm.routes = lambda doi: (_ for _ in () )
    output = tmp_path / "paper.pdf"
    result = app.fetch("10.1234/example", output, use_institution=False)
    assert result.ok
    assert result.route == "openalex"
    assert result.layer == "open_access"
    assert output.read_bytes() == PDF


def test_pipeline_emits_sanitized_progress_events(tmp_path: Path):
    events = []
    app = DOI2PDF(Settings(translator_enabled=False), http=FakeHttp())
    app.oa.candidates = lambda doi: ([Candidate("https://example.org/good.pdf", "openalex", "open_access")], [])
    app.tdm.routes = lambda doi: (_ for _ in ())
    result = app.fetch("10.1234/example", tmp_path / "paper.pdf", use_institution=False, progress=events.append)
    assert result.ok
    assert events[0]["stage"] == "resolving"
    assert events[-1]["stage"] == "complete"
    assert events[-1]["percent"] == 100
    assert all("url" not in event and "detail" not in event for event in events)


def test_manual_resolver_is_final_layer(tmp_path: Path):
    settings = Settings(
        translator_enabled=False,
        resolver_template="https://resolver.example/?doi={doi}",
    )
    app = DOI2PDF(settings, http=FakeHttp())
    app.oa.candidates = lambda doi: ([], [])
    app.tdm.routes = lambda doi: (_ for _ in ())
    result = app.fetch("10.1234/example", tmp_path / "paper.pdf", use_institution=False)
    assert not result.ok
    assert result.resolver_url == "https://resolver.example/?doi=10.1234/example"
    assert result.attempts[-1].layer == "resolver"
    assert result.attempts[-1].status == "manual_required"


def test_manual_resolver_completes_progress(tmp_path: Path):
    events = []
    app = DOI2PDF(Settings(translator_enabled=False), http=FakeHttp())
    app.oa.candidates = lambda doi: ([], [])
    app.tdm.routes = lambda doi: (_ for _ in ())
    app.fetch("10.1234/example", tmp_path / "paper.pdf", use_institution=False, progress=events.append)
    assert events[-1]["stage"] == "resolver"
    assert events[-1]["status"] == "manual_required"


def test_institution_route_and_entitlement_are_preserved(tmp_path: Path):
    app = DOI2PDF(Settings(translator_enabled=False, network_mode="campus", openathens_redirector_prefix="https://go.openathens.net/redirector/example?url="), http=FakeHttp())
    app.oa.candidates = lambda doi: ([], [])
    app.tdm.routes = lambda doi: (_ for _ in ())
    app.institution.fetch = lambda doi: InstitutionResult(PDF, "openathens:nejm:tpl", "pdf", {"subscribed": True, "covered": True})
    result = app.fetch("10.1056/NEJMoa1", tmp_path / "paper.pdf")
    assert result.ok and result.route == "openathens:nejm:tpl"
    assert result.metadata["entitlement"]["covered"] is True


def test_off_campus_mode_skips_institution_even_when_requested(tmp_path: Path):
    app = DOI2PDF(Settings(translator_enabled=False, network_mode="off_campus"), http=FakeHttp())
    app.oa.candidates = lambda doi: ([], [])
    app.tdm.routes = lambda doi: (_ for _ in ())
    called = {"value": False}

    def fail_if_called(doi):
        called["value"] = True
        raise AssertionError("institution.fetch should not run off-campus")

    app.institution.fetch = fail_if_called
    result = app.fetch("10.1056/NEJMoa1", tmp_path / "paper.pdf", use_institution=True)
    assert not result.ok
    assert called["value"] is False


def test_tdm_shares_the_http_client_session():
    app = DOI2PDF(Settings(translator_enabled=False))
    assert app.tdm.session is app.http.session


def test_translator_gets_its_own_session_without_the_ssrf_guard(tmp_path: Path):
    # The translation-server is user-configured and typically loopback (see
    # README); it must not inherit HttpClient's SSRF guard, which would refuse
    # every request to it as a "private host".
    import http.server
    import socketserver
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = b"[]"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        settings = Settings(translator_url=f"http://127.0.0.1:{server.server_address[1]}")
        app = DOI2PDF(settings)
        assert app.translator.session is not app.http.session
        assert app.translator.search("10.1234/example") == []
    finally:
        server.shutdown()
