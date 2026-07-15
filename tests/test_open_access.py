import sqlite3

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
        "unpaywall", "semantic_scholar", "openalex", "europe_pmc"
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
