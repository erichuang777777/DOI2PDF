from doi2pdf.batch_journal import append, attempted_keys, successful_entries, write_manual_review


def test_batch_journal_resume_and_success_entries(tmp_path):
    log = tmp_path / "batch.jsonl"
    append(log, {"item_key": "SUCCESS1", "doi": "10.1/a", "title": "A", "status": "success", "path": "a.pdf", "route": "openalex"})
    append(log, {"item_key": "FAILED01", "doi": "10.1/b", "title": "B", "status": "no_pdf"})
    assert attempted_keys(log) == {"SUCCESS1", "FAILED01"}
    assert attempted_keys(log, retry_failed=True) == {"SUCCESS1"}
    assert successful_entries(log) == [{"key": "SUCCESS1", "filepath": "a.pdf"}]
    assert "https://" not in log.read_text(encoding="utf-8")


def test_manual_review_contains_only_latest_failures(tmp_path):
    log = tmp_path / "batch.jsonl"
    output = tmp_path / "review.html"
    append(log, {"item_key": "RECOVER1", "doi": "10.1/a", "title": "Recovered", "status": "no_pdf"})
    append(log, {"item_key": "RECOVER1", "doi": "10.1/a", "title": "Recovered", "status": "success", "path": "a.pdf"})
    append(log, {"item_key": "FAILED01", "doi": "10.1/b", "title": "Still failed", "status": "error"})
    count = write_manual_review(log, output, "https://resolver.example/?doi={doi}")
    text = output.read_text(encoding="utf-8")
    assert count == 1
    assert "Still failed" in text
    assert "Recovered" not in text
    assert "resolver.example" in text
