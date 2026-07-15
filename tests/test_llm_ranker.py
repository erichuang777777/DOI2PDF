import json

from doi2pdf.config import Settings
from doi2pdf.llm_ranker import rank


class FakeResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": '{"candidate_id": 2, "reason": "primary PDF"}'}}]}


def test_llm_ranker_sends_sanitized_candidates(monkeypatch):
    recorded = {}

    def post(url, **kwargs):
        recorded.update({"url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr("doi2pdf.llm_ranker.requests.post", post)
    settings = Settings(llm_enabled=True, llm_base_url="https://llm.example/v1", llm_model="ranker", llm_api_key="secret")
    selected = rank(settings, "publisher.example", [
        {"id": 1, "text": "Supplement", "aria": "", "href": "https://publisher.example/s.pdf?token=do-not-send"},
        {"id": 2, "text": "Download PDF", "aria": "Full text", "href": "https://publisher.example/article/main.pdf?sig=private"},
    ])
    assert selected == 2
    serialized = json.dumps(recorded["json"])
    assert "do-not-send" not in serialized and "private" not in serialized
    assert "/article/main.pdf" in serialized
    assert recorded["headers"]["Authorization"] == "Bearer secret"


def test_llm_ranker_is_off_by_default(monkeypatch):
    monkeypatch.setattr("doi2pdf.llm_ranker.requests.post", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network")))
    assert rank(Settings(), "publisher.example", [{"id": 1, "href": "/paper.pdf"}]) is None
