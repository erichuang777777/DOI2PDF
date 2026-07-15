from doi2pdf.config import Settings
from doi2pdf.translator import ZoteroTranslatorClient


class Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_uses_injected_session_instead_of_the_requests_module(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("should have used the injected session, not requests.post")

    monkeypatch.setattr("doi2pdf.translator.requests.post", fail_if_called)

    class FakeSession:
        def __init__(self):
            self.calls = []

        def post(self, url, **kwargs):
            self.calls.append(url)
            return Response([{"title": "Example"}])

    session = FakeSession()
    client = ZoteroTranslatorClient(Settings(), session=session)
    assert client.session is session
    items = client.search("10.1234/example")
    assert items == [{"title": "Example"}]
    assert session.calls == [f"{client.base}/search"]
