from doi2pdf.config import Settings
from doi2pdf.open_access import OpenAccessResolver


class FakeHttp:
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
