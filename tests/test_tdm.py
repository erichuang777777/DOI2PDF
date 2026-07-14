from doi2pdf.config import Settings
from doi2pdf.http import PDF_MAGIC
from doi2pdf.tdm import TDMResolver


PDF = PDF_MAGIC + b" test\n" + b"0" * 2048


class Response:
    def __init__(self, content=b"", status=200, payload=None):
        self.content = content
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


def test_elsevier_uses_official_endpoint_and_key(monkeypatch):
    seen = {}

    def fake_get(url, **kwargs):
        seen.update(url=url, **kwargs)
        return Response(PDF)

    monkeypatch.setattr("doi2pdf.tdm.requests.get", fake_get)
    content, status = TDMResolver(Settings(elsevier_api_key="key")).elsevier("10.1016/test")
    assert content == PDF and status == "pdf"
    assert seen["url"].startswith("https://api.elsevier.com/content/article/doi/")
    assert seen["headers"]["X-ELS-APIKey"] == "key"


def test_wiley_encodes_doi_and_uses_tdm_token(monkeypatch):
    seen = {}

    def fake_get(url, **kwargs):
        seen.update(url=url, **kwargs)
        return Response(PDF)

    monkeypatch.setattr("doi2pdf.tdm.requests.get", fake_get)
    content, _ = TDMResolver(Settings(wiley_tdm_token="token")).wiley("10.1002/a/b")
    assert content == PDF
    assert "10.1002%2Fa%2Fb" in seen["url"]
    assert seen["headers"]["Wiley-TDM-Client-Token"] == "token"


def test_springer_prefers_official_oa_api_pdf(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        if "openaccess/json" in url:
            return Response(payload={"records": [{"url": [{"format": "pdf", "value": "https://springer.example/paper.pdf"}]}]})
        return Response(PDF)

    monkeypatch.setattr("doi2pdf.tdm.requests.get", fake_get)
    content, _ = TDMResolver(Settings(springer_api_key="key")).springer("10.1007/test")
    assert content == PDF
    assert calls[0][0] == "https://api.springernature.com/openaccess/json"
    assert calls[0][1]["params"]["api_key"] == "key"
    assert calls[1][0] == "https://springer.example/paper.pdf"
