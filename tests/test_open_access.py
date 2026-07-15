import sqlite3
import time

from doi2pdf.config import Settings
from doi2pdf.open_access import OpenAccessResolver


class FakeHttp:
    def get_content(self, url, **kwargs):
        return b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>'

    def get_json(self, url, **kwargs):
        if "unpaywall" in url:
            return {
                "best_oa_location": {
                    "url_for_pdf": "https://repo.example/a.pdf",
                    "url_for_landing_page": "https://repo.example/a",
                },
                "oa_locations": [
                    {"url_for_pdf": "https://repo.example/a.pdf"},
                    {"url": "https://other.example/article"},
                ],
            }
        if "semanticscholar" in url:
            return {"openAccessPdf": {"url": "https://s2.example/a.pdf"}}
        if "openalex" in url:
            return {
                "best_oa_location": {"pdf_url": "https://oa.example/a.pdf"},
                "locations": [
                    {"pdf_url": "https://oa.example/a.pdf", "is_oa": True},
                    {"landing_page_url": "https://archive.example/a", "is_oa": True},
                    {"pdf_url": "https://paywall.example/a.pdf", "is_oa": False},
                ],
            }
        return {"records": [{"pmcid": "PMC123"}]}


def test_all_oa_locations_and_sources_are_returned():
    settings = Settings(unpaywall_email="a@example.org", contact_email="a@example.org")
    candidates, errors = OpenAccessResolver(settings, FakeHttp()).candidates("10.1/example")
    assert not errors
    assert {candidate.source for candidate in candidates} == {
        "unpaywall", "semantic_scholar", "openalex", "europe_pmc", "pmc_direct"
    }
    assert sum(candidate.url == "https://repo.example/a.pdf" for candidate in candidates) == 1
    assert any(candidate.url.endswith("PMC123?pdf=render") for candidate in candidates)
    assert not any("paywall.example" in candidate.url for candidate in candidates)


def test_paper_radar_read_only_fallback(tmp_path):
    database = tmp_path / "radar.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("create table papers(doi text,oa_pdf_url text)")
        connection.execute("insert into papers values(?,?)", ("10.1/example", "https://repo.example/landing"))
    resolver = OpenAccessResolver(Settings(paper_radar_db=database), FakeHttp())
    candidates = resolver.paper_radar("10.1/example")
    assert candidates[0].source == "paper_radar"
    assert candidates[0].kind == "landing"


def test_europe_pmc_uses_current_ncbi_endpoint():
    class RecordingHttp(FakeHttp):
        def get_json(self, url, **kwargs):
            self.url = url
            return {"records": []}

    http = RecordingHttp()
    OpenAccessResolver(Settings(), http).europe_pmc("10.1/example")
    assert http.url == "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/"


def test_arxiv_doi_is_mapped_directly_without_search():
    resolver = OpenAccessResolver(Settings(), FakeHttp())
    candidate = resolver.arxiv("10.48550/arXiv.2401.01234")[0]
    assert candidate.url == "https://arxiv.org/pdf/2401.01234.pdf"
    assert candidate.source == "arxiv"


def test_arxiv_atom_search_returns_pdf_link():
    class AtomHttp(FakeHttp):
        def get_content(self, url, **kwargs):
            return b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
              <link title="pdf" href="https://arxiv.org/pdf/2401.01234v2" />
            </entry></feed>'''

    candidate = OpenAccessResolver(Settings(), AtomHttp()).arxiv("10.1/example")[0]
    assert candidate.url == "https://arxiv.org/pdf/2401.01234v2"


def test_europe_pmc_rest_backend_candidate():
    class EuropeHttp(FakeHttp):
        def get_json(self, url, **kwargs):
            return {"resultList": {"result": [{"pmcid": "PMC123", "fullTextIdList": {"fullTextId": ["PMC123"]}}]}}

    candidate = OpenAccessResolver(Settings(), EuropeHttp()).europe_pmc_search("10.1/example")[0]
    assert "ptpmcrender.fcgi?accid=PMC123" in candidate.url
    assert candidate.source == "europe_pmc_search"


def test_pmc_direct_uses_ncbi_front_end():
    class IdconvHttp(FakeHttp):
        def get_json(self, url, **kwargs):
            return {"records": [{"pmcid": "PMC456"}]}

    candidate = OpenAccessResolver(Settings(), IdconvHttp()).pmc_direct("10.1/example")[0]
    assert candidate.url == "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC456/pdf/"
    assert candidate.source == "pmc_direct"


def test_europe_pmc_and_pmc_direct_share_a_single_idconv_call():
    class CountingHttp(FakeHttp):
        def __init__(self):
            self.calls = 0

        def get_json(self, url, **kwargs):
            self.calls += 1
            return {"records": [{"pmcid": "PMC456"}]}

    http = CountingHttp()
    resolver = OpenAccessResolver(Settings(), http)
    assert resolver.europe_pmc("10.1/example")[0].source == "europe_pmc"
    assert resolver.pmc_direct("10.1/example")[0].source == "pmc_direct"
    assert http.calls == 1


def test_crossref_links_extracts_pdf_content_type():
    class CrossrefHttp(FakeHttp):
        def get_json(self, url, **kwargs):
            return {"message": {"link": [
                {"URL": "https://publisher.example/a.pdf", "content-type": "application/pdf"},
                {"URL": "https://publisher.example/a.xml", "content-type": "application/xml"},
            ]}}

    candidates = OpenAccessResolver(Settings(contact_email="a@example.org"), CrossrefHttp()).crossref_links("10.1/example")
    assert [candidate.url for candidate in candidates] == ["https://publisher.example/a.pdf"]
    assert candidates[0].source == "crossref"


def test_core_requires_api_key_and_returns_download_url():
    class CoreHttp(FakeHttp):
        def get_json(self, url, **kwargs):
            self.headers = kwargs.get("headers")
            return {"results": [{"downloadUrl": "https://core.example/a.pdf"}]}

    resolver_without_key = OpenAccessResolver(Settings(), CoreHttp())
    assert resolver_without_key.core("10.1/example") == []

    http = CoreHttp()
    resolver = OpenAccessResolver(Settings(core_api_key="core-key"), http)
    candidates = resolver.core("10.1/example")
    assert candidates[0].url == "https://core.example/a.pdf"
    assert candidates[0].source == "core"
    assert http.headers["Authorization"] == "Bearer core-key"


def test_doaj_extracts_fulltext_link():
    class DoajHttp(FakeHttp):
        def get_json(self, url, **kwargs):
            return {"results": [{"bibjson": {"link": [
                {"type": "fulltext", "url": "https://doaj.example/a.pdf"},
                {"type": "homepage", "url": "https://doaj.example/home"},
            ]}}]}

    candidates = OpenAccessResolver(Settings(), DoajHttp()).doaj("10.1/example")
    assert [candidate.url for candidate in candidates] == ["https://doaj.example/a.pdf"]
    assert candidates[0].source == "doaj"


def test_candidates_queries_indexes_concurrently():
    delay = 0.2

    class SlowHttp(FakeHttp):
        def get_json(self, url, **kwargs):
            time.sleep(delay)
            return super().get_json(url, **kwargs)

        def get_content(self, url, **kwargs):
            time.sleep(delay)
            return super().get_content(url, **kwargs)

    settings = Settings(unpaywall_email="a@example.org", contact_email="a@example.org")
    started = time.monotonic()
    OpenAccessResolver(settings, SlowHttp()).candidates("10.1/example")
    elapsed = time.monotonic() - started
    # Sequentially, the ~7 sources that actually hit the network here would take
    # >= 7 * delay. Run concurrently, elapsed should stay close to one delay.
    assert elapsed < delay * 3


def test_candidates_preserve_priority_order_regardless_of_completion_order():
    from doi2pdf.models import Candidate

    resolver = OpenAccessResolver(Settings(), FakeHttp())
    # Silence every source except the two under test.
    for name in ("openalex", "crossref_links", "europe_pmc", "europe_pmc_search",
                 "pmc_direct", "arxiv", "core", "doaj", "paper_radar"):
        setattr(resolver, name, lambda doi: [])

    def slow_but_first_in_priority(doi):
        time.sleep(0.15)
        return [Candidate("https://first.example/a.pdf", "unpaywall", "open_access")]

    def instant_but_second_in_priority(doi):
        return [Candidate("https://second.example/a.pdf", "semantic_scholar", "open_access")]

    resolver.unpaywall = slow_but_first_in_priority
    resolver.semantic_scholar = instant_but_second_in_priority

    candidates, errors = resolver.candidates("10.1/example")
    assert not errors
    # semantic_scholar finishes first, but unpaywall's higher download priority
    # must still come first in the merged, deduped candidate list.
    assert [candidate.url for candidate in candidates] == [
        "https://first.example/a.pdf", "https://second.example/a.pdf",
    ]
