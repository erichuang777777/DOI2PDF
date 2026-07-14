from pathlib import Path

from doi2pdf.config import Settings
from doi2pdf.http import PDF_MAGIC
from doi2pdf.models import Candidate
from doi2pdf.pipeline import DOI2PDF


PDF = PDF_MAGIC + b" test\n" + b"0" * 2048


class FakeHttp:
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
