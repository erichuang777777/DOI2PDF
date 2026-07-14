import pytest

from doi2pdf.normalize import normalize_doi


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("10.1186/S12984-023-01168-X", "10.1186/s12984-023-01168-x"),
        ("doi: 10.1002/example.", "10.1002/example"),
        ("https://doi.org/10.1016/j.test.2026.1", "10.1016/j.test.2026.1"),
    ],
)
def test_normalize_doi(value, expected):
    assert normalize_doi(value) == expected


def test_rejects_missing_doi():
    with pytest.raises(ValueError):
        normalize_doi("not an identifier")


def test_cli_reports_invalid_identifier_without_traceback(capsys, monkeypatch):
    from doi2pdf import cli

    class InvalidIdentifiers:
        @staticmethod
        def resolve(value):
            raise ValueError("Could not resolve a trustworthy DOI")

    class FakeApp:
        def __init__(self, settings):
            self.identifiers = InvalidIdentifiers()

    monkeypatch.setattr(cli, "DOI2PDF", FakeApp)
    assert cli.main(["resolve", "not an identifier unlikely to exist"]) == 2
    assert "Could not resolve" in capsys.readouterr().err
