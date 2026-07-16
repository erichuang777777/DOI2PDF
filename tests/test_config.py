import doi2pdf.config as config
from doi2pdf.config import Settings


def test_invalid_numeric_environment_is_reported_without_crashing(monkeypatch):
    monkeypatch.setenv("DOI2PDF_REQUEST_TIMEOUT_S", "not-a-number")
    monkeypatch.setenv("DOI2PDF_HTTP_MAX_RETRIES", "also-bad")
    settings = Settings.from_env()
    assert settings.request_timeout_s == 45
    assert settings.http_max_retries == 3
    assert "DOI2PDF_REQUEST_TIMEOUT_S must be a valid int." in settings.validate()
    assert "DOI2PDF_HTTP_MAX_RETRIES must be a valid int." in settings.validate()


def test_auto_network_mode_matches_configured_local_cidr(monkeypatch):
    monkeypatch.setattr(config, "_local_ip_addresses", lambda: {"140.112.8.9", "fe80::1%4"})
    assert Settings(campus_cidrs=("140.112.0.0/16",)).effective_network_mode() == "campus"
    assert Settings(campus_cidrs=("10.0.0.0/8",)).effective_network_mode() == "off_campus"


def test_access_urls_reject_embedded_credentials():
    settings = Settings(
        contact_email="user@example.org",
        openathens_redirector_prefix="https://user:secret@go.openathens.net/redirector/example?url=",
        resolver_template="https://user:secret@resolver.example/?doi={doi}",
    )
    issues = settings.validate()
    assert any("OPENATHENS_REDIRECTOR_PREFIX cannot contain credentials" in issue for issue in issues)
    assert any("LIBRARY_RESOLVER_TEMPLATE" in issue for issue in issues)


def test_browser_use_is_disabled_by_default_and_requires_explicit_opt_in(monkeypatch):
    monkeypatch.delenv("DOI2PDF_BROWSER_USE_ENABLED", raising=False)
    assert Settings.from_env().browser_use_enabled is False
    monkeypatch.setenv("DOI2PDF_BROWSER_USE_ENABLED", "true")
    assert Settings.from_env().browser_use_enabled is True
