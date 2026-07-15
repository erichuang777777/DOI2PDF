import sqlite3
from pathlib import Path

from doi2pdf.config import Settings
from doi2pdf.holdings import Holdings, coverage_ok


def make_db(path: Path):
    with sqlite3.connect(path) as connection:
        connection.execute("create table journals(title text,publisher text,issn_print text,issn_e text,is_free int,coverage text)")
        connection.execute("insert into journals values(?,?,?,?,?,?)", ("Example Journal", "Wiley", "1234-5678", "", 0, "Available from 1997 until 2013. Available from 2019"))


def test_multiple_coverage_ranges_are_respected():
    assert coverage_ok("Available from 1997 until 2013. Available from 2019", 2026) is True
    assert coverage_ok("Available from 1997 until 2013. Available from 2019", 2015) is False
    assert coverage_ok("unknown", 2026) is None


def test_holdings_is_read_only_and_matches_issn(tmp_path: Path):
    database = tmp_path / "holdings.sqlite"
    make_db(database)
    holdings = Holdings(Settings(holdings_db=database, browser_profile=tmp_path / "profile"))
    holdings.doi_metadata = lambda doi: {"issns": ["1234-5678"], "journal": "Example Journal", "year": 2026}
    result = holdings.check("10.1234/example")
    assert result["subscribed"] is True
    assert result["covered"] is True
    assert result["platform"] == "Wiley"
    assert holdings.platforms() == [{"platform": "Wiley", "journals": 1}]
