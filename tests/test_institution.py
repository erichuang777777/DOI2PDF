import json
import time
from pathlib import Path

import pytest

from doi2pdf.config import Settings
from doi2pdf.institution import (
    DailyLimitReached,
    InstitutionalBrowser,
    ProfileBusy,
    enforce_daily_limit,
    institution_daily_count,
    profile_lock,
)


def test_openathens_target_is_percent_encoded():
    browser = InstitutionalBrowser(
        Settings(openathens_redirector_prefix="https://go.openathens.net/redirector/example.edu?url=")
    )
    url, family = browser.access_url("10.1002/test")
    assert family == "openathens"
    assert url.endswith("https%3A%2F%2Fdoi.org%2F10.1002%2Ftest")


def test_profile_lock_is_exclusive_and_recovers_stale_holder(tmp_path: Path):
    with profile_lock(tmp_path):
        with pytest.raises(ProfileBusy):
            with profile_lock(tmp_path):
                pass
    lock = tmp_path / ".doi2pdf.lock"
    lock.write_text(json.dumps({"pid": 99999999, "time": time.time() - 3600}), encoding="utf-8")
    with profile_lock(tmp_path):
        assert lock.exists()
    assert not lock.exists()


def test_daily_limit_counts_fetches_only(tmp_path: Path):
    log = tmp_path / "access_log.jsonl"
    today = time.strftime("%Y-%m-%d", time.localtime())
    log.write_text("\n".join([
        json.dumps({"date": today, "kind": "fetch"}),
        json.dumps({"date": today, "kind": "login"}),
        "not-json",
    ]), encoding="utf-8")
    assert institution_daily_count(log) == 1
    with pytest.raises(DailyLimitReached):
        enforce_daily_limit(log, 1)


def test_rate_settings_cannot_be_disabled(monkeypatch):
    monkeypatch.setenv("DOI2PDF_INSTITUTION_INTERVAL_S", "0")
    monkeypatch.setenv("DOI2PDF_MAX_INSTITUTION_REQUESTS_PER_DAY", "99999")
    settings = Settings.from_env()
    assert settings.min_institution_interval_s == 15
    assert settings.max_institution_requests_per_day == 100


def test_placeholder_email_requires_first_run_setup():
    settings = Settings(contact_email="you@example.org", setup_complete=True)
    assert settings.needs_setup()
    assert "real contact email" in settings.validate()[0]
