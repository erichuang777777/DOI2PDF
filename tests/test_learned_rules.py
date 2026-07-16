import pytest

from doi2pdf.learned_rules import RuleStore


def test_rule_is_promoted_only_after_two_validated_successes(tmp_path):
    store = RuleStore(tmp_path / "learned_pdf_rules.json")
    first = store.remember("journals.example.org", "a.download-pdf", text_hint="Download PDF", source="llm")
    second = store.remember("journals.example.org", "a.download-pdf", text_hint="Download PDF", source="learned")
    assert first["status"] == "provisional"
    assert second["status"] == "verified"
    assert second["successes"] == 2
    raw = (tmp_path / "learned_pdf_rules.json").read_text(encoding="utf-8")
    assert "http" not in raw and "token=" not in raw


def test_rule_disables_after_three_consecutive_failures_and_can_be_forgotten(tmp_path):
    store = RuleStore(tmp_path / "learned_pdf_rules.json")
    store.remember("publisher.example", "#download")
    for _ in range(3):
        store.failed("publisher.example", "#download")
    assert store.list()[0]["status"] == "disabled"
    assert store.list()[0]["enabled"] is False
    assert store.forget("publisher.example") == 1
    assert store.list() == []


def test_rule_rejects_urls_and_signed_query_material(tmp_path):
    store = RuleStore(tmp_path / "rules.json")
    with pytest.raises(ValueError):
        store.remember("publisher.example", "a[href='https://signed.example/file?token=secret']")


def test_corrupt_rule_file_fails_closed(tmp_path):
    path = tmp_path / "rules.json"
    path.write_text("not json", encoding="utf-8")
    assert RuleStore(path).list() == []


def test_injected_signed_selector_is_never_returned(tmp_path):
    path = tmp_path / "rules.json"
    path.write_text('{"rules":[{"host":"publisher.example","selector":"a[href=\\"https://x/pdf?token=secret\\"]"}]}', encoding="utf-8")
    assert RuleStore(path).list() == []
