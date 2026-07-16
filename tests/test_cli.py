import json
import subprocess
import sys
from pathlib import Path

from doi2pdf import cli
from doi2pdf.config import Settings


def test_doctor_json_is_agent_ready_and_accepts_trailing_flag(capsys, monkeypatch):
    monkeypatch.setattr(
        cli.Settings,
        "from_env",
        lambda: Settings(contact_email="agent@example.org", unpaywall_email="agent@example.org", network_mode="campus", openathens_redirector_prefix="https://go.openathens.net/redirector/example?url="),
    )
    assert cli.main(["doctor", "--json"]) == cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["status"] == "ready"
    assert payload["setup_command"] == "doi2pdf-web"
    assert payload["web_setup_complete"] is False
    assert payload["network_mode"] == "campus"
    assert payload["effective_network_mode"] == "campus"
    assert payload["routes"]["open_access"] is True
    assert payload["routes"]["institution"] is True


def test_invalid_identifier_json_stays_on_stdout(capsys, monkeypatch):
    class InvalidIdentifiers:
        @staticmethod
        def resolve(value):
            raise ValueError("Could not resolve a trustworthy DOI")

    class FakeApp:
        def __init__(self, settings):
            self.identifiers = InvalidIdentifiers()

    monkeypatch.setattr(cli, "DOI2PDF", FakeApp)
    assert cli.main(["resolve", "not-a-doi", "--json"]) == cli.EXIT_INPUT_OR_CONFIG
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "invalid_identifier"
    assert captured.err == ""


def test_acceptance_lists_real_cases_and_filters_publisher(capsys):
    assert cli.main(["acceptance", "--publisher", "Elsevier", "--json"]) == cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ready"
    assert payload["count"] == 2
    assert all(row["publisher"] == "Elsevier" for row in payload["cases"])
    assert all(row["doi"].startswith("10.") for row in payload["cases"])


def test_api_check_without_keys_is_explicit_and_does_not_call_network(capsys, monkeypatch):
    monkeypatch.setattr(cli.Settings, "from_env", lambda: Settings())
    assert cli.main(["api-check", "--json"]) == cli.EXIT_INPUT_OR_CONFIG
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "no_keys_configured"
    assert len(payload["results"]) == 6
    assert {row["status"] for row in payload["results"]} == {"not_configured"}


def test_routes_command_exposes_complete_registry_without_secrets(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(cli.Settings, "from_env", lambda: Settings(browser_profile=tmp_path, library_password="secret"))
    assert cli.main(["routes", "--json"]) == cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["registry"]) == 23
    assert "secret" not in str(payload)


def test_holdings_command_explains_missing_database(capsys, monkeypatch):
    monkeypatch.setattr(cli.Settings, "from_env", lambda: Settings())
    assert cli.main(["holdings", "10.1234/example", "--json"]) == cli.EXIT_INPUT_OR_CONFIG
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "not_configured"


def test_rules_command_lists_and_guards_forget(capsys, monkeypatch, tmp_path):
    settings = Settings(browser_profile=tmp_path)
    monkeypatch.setattr(cli.Settings, "from_env", lambda: settings)
    cli.RuleStore(tmp_path / "learned_pdf_rules.json").remember("publisher.example", "#pdf")
    assert cli.main(["rules", "--json"]) == cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1 and payload["rules"][0]["host"] == "publisher.example"
    assert cli.main(["rules", "--forget", "publisher.example", "--json"]) == cli.EXIT_INPUT_OR_CONFIG
    assert json.loads(capsys.readouterr().out)["status"] == "confirmation_required"
    assert cli.main(["rules", "--forget", "publisher.example", "--yes", "--json"]) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out)["removed"] == 1


def test_library_detect_command_is_agent_ready(capsys):
    assert cli.main(["library-detect", "https://login.example.edu/login?url=https://publisher.example/article", "--json"]) == cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "ezproxy_prefix"
    assert payload["updates"]["EZPROXY_PREFIX"].endswith("url=")


def test_batch_zotero_prefetches_openalex_before_the_loop(tmp_path, monkeypatch):
    from doi2pdf.models import FetchResult

    db = tmp_path / "zotero.sqlite"
    db.touch()
    items = [
        {"key": "AAA1AAA1", "title": "One", "doi": "10.1/one", "year": "2020", "author": "Smith"},
        {"key": "BBB2BBB2", "title": "Two", "doi": "10.1/two", "year": "2021", "author": "Jones"},
        {"key": "CCC3CCC3", "title": "Three", "doi": None, "year": None, "author": None},
    ]

    class FakeZoteroLibrary:
        def __init__(self, path):
            pass

        def missing_pdfs(self, limit):
            return items

    prefetch_calls = []

    class FakeOA:
        def prefetch_openalex_batch(self, dois):
            prefetch_calls.append(list(dois))

    class FakeApp:
        def __init__(self, settings):
            self.oa = FakeOA()

        def fetch(self, identifier, output, use_institution):
            return FetchResult(doi=identifier or "unknown", ok=False, path=output)

    monkeypatch.setattr(cli, "ZoteroLibrary", FakeZoteroLibrary)
    monkeypatch.setattr(cli, "DOI2PDF", FakeApp)
    monkeypatch.setattr(
        cli.Settings,
        "from_env",
        lambda: Settings(contact_email="agent@example.org", unpaywall_email="agent@example.org"),
    )

    cli.main([
        "--json", "batch-zotero", "--db", str(db),
        "--output-dir", str(tmp_path / "out"), "--log", str(tmp_path / "log.jsonl"),
    ])

    # Only items with a DOI are worth prefetching; order matches the scan order.
    assert prefetch_calls == [["10.1/one", "10.1/two"]]


def test_batch_zotero_skips_prefetch_for_already_tried_items(tmp_path, monkeypatch):
    from doi2pdf.batch_journal import append as append_batch_log
    from doi2pdf.models import FetchResult

    db = tmp_path / "zotero.sqlite"
    db.touch()
    items = [
        {"key": "AAA1AAA1", "title": "One", "doi": "10.1/one", "year": "2020", "author": "Smith"},
        {"key": "BBB2BBB2", "title": "Two", "doi": "10.1/two", "year": "2021", "author": "Jones"},
    ]
    log_path = tmp_path / "log.jsonl"
    append_batch_log(log_path, {"item_key": "AAA1AAA1", "doi": "10.1/one", "title": "One", "status": "success", "route": "unpaywall", "path": str(tmp_path / "one.pdf")})

    class FakeZoteroLibrary:
        def __init__(self, path):
            pass

        def missing_pdfs(self, limit):
            return items

    prefetch_calls = []

    class FakeOA:
        def prefetch_openalex_batch(self, dois):
            prefetch_calls.append(list(dois))

    class FakeApp:
        def __init__(self, settings):
            self.oa = FakeOA()

        def fetch(self, identifier, output, use_institution):
            return FetchResult(doi=identifier or "unknown", ok=False, path=output)

    monkeypatch.setattr(cli, "ZoteroLibrary", FakeZoteroLibrary)
    monkeypatch.setattr(cli, "DOI2PDF", FakeApp)
    monkeypatch.setattr(
        cli.Settings,
        "from_env",
        lambda: Settings(contact_email="agent@example.org", unpaywall_email="agent@example.org"),
    )

    cli.main([
        "--json", "batch-zotero", "--db", str(db), "--resume",
        "--output-dir", str(tmp_path / "out"), "--log", str(log_path),
    ])

    # AAA1AAA1 already succeeded per the journal; only the untried DOI is prefetched.
    assert prefetch_calls == [["10.1/two"]]


def test_batch_zotero_off_campus_skips_institution_phase(tmp_path, monkeypatch):
    from doi2pdf.models import FetchResult

    db = tmp_path / "zotero.sqlite"
    db.touch()
    items = [
        {"key": "AAA1AAA1", "title": "One", "doi": "10.1/one", "year": "2020", "author": "Smith"},
    ]

    class FakeZoteroLibrary:
        def __init__(self, path):
            pass

        def missing_pdfs(self, limit):
            return items

    class FakeOA:
        def prefetch_openalex_batch(self, dois):
            pass

    fetch_calls = []

    class FakeApp:
        def __init__(self, settings):
            self.oa = FakeOA()

        def fetch(self, identifier, output, use_institution):
            fetch_calls.append(use_institution)
            return FetchResult(doi=identifier or "unknown", ok=False, path=output)

    monkeypatch.setattr(cli, "ZoteroLibrary", FakeZoteroLibrary)
    monkeypatch.setattr(cli, "DOI2PDF", FakeApp)
    monkeypatch.setattr(
        cli.Settings,
        "from_env",
        lambda: Settings(contact_email="agent@example.org", unpaywall_email="agent@example.org", network_mode="off_campus"),
    )

    cli.main([
        "--json", "batch-zotero", "--db", str(db),
        "--output-dir", str(tmp_path / "out"), "--log", str(tmp_path / "log.jsonl"),
    ])

    assert fetch_calls == [False]


def test_skill_installer_dry_run_uses_local_project():
    script = Path("skills/doi2pdf/scripts/install_cli.py")
    completed = subprocess.run(
        [sys.executable, str(script), "--dry-run", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    assert payload["dry_run"] is True
    assert payload["commands"][0][-1].endswith("[web]")
    assert Path(payload["target"]).name == Path.cwd().name
