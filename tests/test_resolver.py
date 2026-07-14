from doi2pdf.config import Settings
from doi2pdf.resolver import IdentifierResolver


class FakeHttp:
    def get_json(self, url, **kwargs):
        if "idconv" in url:
            return {"records": [{"pmid": "12345678", "doi": "10.5555/PUBMED"}]}
        return {
            "message": {
                "items": [
                    {"DOI": "10.5555/wrong", "title": ["A different paper"]},
                    {"DOI": "10.5555/right", "title": ["The exact useful article title"]},
                ]
            }
        }


def test_resolves_pubmed_with_id_converter():
    resolver = IdentifierResolver(Settings(pubmed_api_key="secret"), FakeHttp())
    assert resolver.resolve("PMID:12345678") == "10.5555/pubmed"


def test_resolves_title_only_above_similarity_threshold():
    resolver = IdentifierResolver(Settings(), FakeHttp())
    assert resolver.resolve("The exact useful article title") == "10.5555/right"
