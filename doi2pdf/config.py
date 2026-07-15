from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PLACEHOLDER_EMAILS = {"you@example.org", "your@email.com", "evolved@zotero.org"}


@dataclass
class Settings:
    contact_email: str = ""
    unpaywall_email: str = ""
    pubmed_api_key: str = ""
    semantic_scholar_api_key: str = ""
    elsevier_api_key: str = ""
    elsevier_insttoken: str = ""
    wiley_tdm_token: str = ""
    springer_api_key: str = ""
    translator_url: str = "http://127.0.0.1:1969"
    translator_enabled: bool = True
    openathens_redirector_prefix: str = ""
    ezproxy_prefix: str = ""
    ezproxy_suffix: str = ""
    library_login_url: str = ""
    library_username: str = ""
    library_password: str = ""
    library_user_selector: str = "input[name='user'],#id_username"
    library_password_selector: str = "input[name='pass'],#id_password"
    library_submit_selector: str = "form button[type='submit'],form input[type='submit']"
    resolver_template: str = ""
    paper_radar_db: Path | None = None
    holdings_db: Path | None = None
    llm_enabled: bool = False
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
    download_dir: Path = field(default_factory=lambda: Path("downloads"))
    setup_complete: bool = False
    browser_profile: Path = field(default_factory=lambda: Path.home() / ".doi2pdf" / "browser")
    browser_headless: bool = False
    request_timeout_s: int = 45
    min_institution_interval_s: float = 15.0
    max_institution_requests_per_day: int = 100

    @classmethod
    def from_env(cls) -> "Settings":
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass
        contact = os.getenv("DOI2PDF_CONTACT_EMAIL", "")
        return cls(
            contact_email=contact,
            unpaywall_email=os.getenv("UNPAYWALL_EMAIL", contact),
            pubmed_api_key=os.getenv("PUBMED_API_KEY", ""),
            semantic_scholar_api_key=os.getenv("S2_API_KEY", ""),
            elsevier_api_key=os.getenv("ELSEVIER_TDM_KEY", ""),
            elsevier_insttoken=os.getenv("ELSEVIER_INSTTOKEN", ""),
            wiley_tdm_token=os.getenv("WILEY_TDM_TOKEN", ""),
            springer_api_key=os.getenv("SPRINGER_API_KEY", ""),
            translator_url=os.getenv("ZOTERO_TRANSLATION_SERVER", "http://127.0.0.1:1969").rstrip("/"),
            translator_enabled=_bool("DOI2PDF_TRANSLATOR_ENABLED", True),
            openathens_redirector_prefix=os.getenv("OPENATHENS_REDIRECTOR_PREFIX", ""),
            ezproxy_prefix=os.getenv("EZPROXY_PREFIX", ""),
            ezproxy_suffix=os.getenv("EZPROXY_SUFFIX", ""),
            library_login_url=os.getenv("LIBRARY_LOGIN_URL", ""),
            library_username=os.getenv("LIBRARY_USERNAME", ""),
            library_password=os.getenv("LIBRARY_PASSWORD", ""),
            library_user_selector=os.getenv("LIBRARY_USER_SELECTOR", "input[name='user'],#id_username"),
            library_password_selector=os.getenv("LIBRARY_PASSWORD_SELECTOR", "input[name='pass'],#id_password"),
            library_submit_selector=os.getenv("LIBRARY_SUBMIT_SELECTOR", "form button[type='submit'],form input[type='submit']"),
            resolver_template=os.getenv("LIBRARY_RESOLVER_TEMPLATE", ""),
            paper_radar_db=Path(value) if (value := os.getenv("PAPER_RADAR_DB", "")) else None,
            holdings_db=Path(value) if (value := os.getenv("HOLDINGS_DB", "")) else None,
            llm_enabled=_bool("DOI2PDF_LLM_ENABLED", False),
            llm_base_url=os.getenv("DOI2PDF_LLM_BASE_URL", "").rstrip("/"),
            llm_model=os.getenv("DOI2PDF_LLM_MODEL", ""),
            llm_api_key=os.getenv("DOI2PDF_LLM_API_KEY", ""),
            download_dir=Path(os.getenv("DOWNLOAD_DIR", "downloads")),
            setup_complete=_bool("DOI2PDF_SETUP_COMPLETE", False),
            browser_profile=Path(os.getenv("DOI2PDF_BROWSER_PROFILE", str(Path.home() / ".doi2pdf" / "browser"))),
            browser_headless=_bool("DOI2PDF_BROWSER_HEADLESS", False),
            request_timeout_s=int(os.getenv("DOI2PDF_REQUEST_TIMEOUT_S", "45")),
            # Institutional automation always retains a courtesy floor. This is not
            # configurable to zero because one user's burst can block the whole campus.
            min_institution_interval_s=max(15.0, float(os.getenv("DOI2PDF_INSTITUTION_INTERVAL_S", "15"))),
            max_institution_requests_per_day=max(
                1, min(100, int(os.getenv("DOI2PDF_MAX_INSTITUTION_REQUESTS_PER_DAY", "100")))
            ),
        )

    def resolver_url(self, doi: str) -> str | None:
        if not self.resolver_template:
            return None
        return self.resolver_template.format(doi=doi)

    def validate(self) -> list[str]:
        issues: list[str] = []
        email = (self.contact_email or self.unpaywall_email).strip().lower()
        if not email or email in PLACEHOLDER_EMAILS or not EMAIL_RE.match(email):
            issues.append("Enter your real contact email for polite scholarly API access.")
        for name, value in (
            ("OPENATHENS_REDIRECTOR_PREFIX", self.openathens_redirector_prefix),
            ("EZPROXY_PREFIX", self.ezproxy_prefix),
        ):
            if value and not value.startswith("https://"):
                issues.append(f"{name} must start with https://")
        if self.openathens_redirector_prefix and "url=" not in self.openathens_redirector_prefix:
            issues.append("OPENATHENS_REDIRECTOR_PREFIX should end with ?url= or &url=.")
        if self.ezproxy_suffix and any(part in self.ezproxy_suffix for part in ("/", "?", "#")):
            issues.append("EZPROXY_SUFFIX must be only a host or host:port, without a URL path.")
        if self.library_login_url and not self.library_login_url.startswith("https://"):
            issues.append("LIBRARY_LOGIN_URL must start with https://")
        if bool(self.library_username) != bool(self.library_password):
            issues.append("LIBRARY_USERNAME and LIBRARY_PASSWORD must be configured together.")
        if self.resolver_template and "{doi}" not in self.resolver_template:
            issues.append("LIBRARY_RESOLVER_TEMPLATE must contain {doi}.")
        if self.llm_enabled:
            if not self.llm_base_url or not self.llm_model:
                issues.append("LLM-assisted discovery requires DOI2PDF_LLM_BASE_URL and DOI2PDF_LLM_MODEL.")
            elif not (self.llm_base_url.startswith("https://") or re.match(r"^http://(?:127\.0\.0\.1|localhost)(?::\d+)?(?:/|$)", self.llm_base_url)):
                issues.append("DOI2PDF_LLM_BASE_URL must use HTTPS or a loopback HTTP endpoint.")
            else:
                parts = urlsplit(self.llm_base_url)
                if parts.username or parts.password or parts.query or parts.fragment:
                    issues.append("DOI2PDF_LLM_BASE_URL cannot contain credentials, query strings, or fragments.")
        return issues

    def needs_setup(self) -> bool:
        return not self.setup_complete or bool(self.validate())
