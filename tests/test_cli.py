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
        lambda: Settings(contact_email="agent@example.org", unpaywall_email="agent@example.org"),
    )
    assert cli.main(["doctor", "--json"]) == cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["status"] == "ready"
    assert payload["setup_command"] == "doi2pdf-web"
    assert payload["web_setup_complete"] is False
    assert payload["routes"]["open_access"] is True


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
    assert len(payload["results"]) == 5
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
