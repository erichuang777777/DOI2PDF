import json

from doi2pdf.route_health import summary


def test_route_health_counts_blocks_and_subscribed_gaps(tmp_path):
    log = tmp_path / "access_log.jsonl"
    events = [
        {"kind": "route", "prefix": "10.1056", "status": "pdf"},
        {"kind": "route", "prefix": "10.1056", "status": "cf_block"},
        {"kind": "route", "prefix": "10.9999", "status": "no_route", "subscribed": True},
    ]
    log.write_text("\n".join(json.dumps(row) for row in events), encoding="utf-8")
    result = summary(log)
    nejm = next(row for row in result["routes"] if row["prefix"] == "10.1056")
    assert result["blocks"] == 1
    assert result["subscribed_route_gaps"] == ["10.9999"]
    assert nejm["pdf"] == 1 and nejm["failures"] == 1


def test_learned_pdf_status_counts_as_success(tmp_path):
    log = tmp_path / "access_log.jsonl"
    log.write_text(json.dumps({"kind": "route", "prefix": "10.1056", "status": "pdf_llm_ranked"}) + "\n", encoding="utf-8")
    result = summary(log)
    nejm = next(row for row in result["routes"] if row["prefix"] == "10.1056")
    assert nejm["pdf"] == 1 and nejm["failures"] == 0
