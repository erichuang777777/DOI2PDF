from doi2pdf.acceptance import corpus
from doi2pdf.api_probe import probe_all
from doi2pdf.config import Settings


def test_live_corpus_is_small_varied_and_not_a_bulk_fixture():
    rows = corpus()
    assert 5 <= len(rows) <= 10
    assert len({row["publisher"] for row in rows}) >= 5
    assert len({row["doi"] for row in rows}) == len(rows)
    assert all(row["source_url"].startswith("https://") for row in rows)
    assert all(row["baseline"] in {"not_retrieved_without_access", "timed_out_without_access"} for row in rows)
    assert any(
        row["doi"] == "10.1056/NEJMoa2600157"
        and row["publisher"] == "New England Journal of Medicine"
        and row["source_url"] == "https://www.nejm.org/doi/pdf/10.1056/NEJMoa2600157"
        for row in rows
    )


def test_unconfigured_api_probe_requires_no_mock_or_network():
    rows = probe_all(Settings())
    assert len(rows) == 6
    assert all(not row["configured"] and row["status"] == "not_configured" for row in rows)
