from __future__ import annotations

from urllib.parse import quote

import requests

from ._version import __version__
from .config import Settings
from .http import looks_like_pdf


class TDMResolver:
    def __init__(self, settings: Settings, session: requests.Session | None = None):
        self.settings = settings
        # Defaulting to the `requests` module (not a Session) preserves the exact
        # prior per-call behavior when no shared session is supplied; the module's
        # top-level get() has the same signature as Session.get().
        self.session = session or requests
        contact = f" (mailto:{settings.contact_email})" if settings.contact_email else ""
        self.user_agent = f"DOI2PDF/{__version__}{contact}"

    def _get(self, url: str, headers: dict[str, str]) -> tuple[bytes | None, str]:
        try:
            response = self.session.get(url, headers=headers, timeout=max(5, self.settings.request_timeout_s))
        except requests.RequestException as exc:
            return None, f"request_error:{exc.__class__.__name__}"
        if response.status_code != 200:
            return None, f"http_{response.status_code}"
        return (response.content, "pdf") if looks_like_pdf(response.content) else (None, "not_pdf")

    def routes(self, doi: str):
        low = doi.lower()
        if low.startswith("10.1016"):
            yield "elsevier", self.elsevier
        if low.startswith(("10.1002", "10.1111")):
            yield "wiley", self.wiley
        if low.startswith(("10.1007", "10.1186")):
            yield "springer", self.springer

    def elsevier(self, doi: str) -> tuple[bytes | None, str]:
        if not self.settings.elsevier_api_key:
            return None, "missing_ELSEVIER_TDM_KEY"
        headers = {"Accept": "application/pdf", "X-ELS-APIKey": self.settings.elsevier_api_key, "User-Agent": self.user_agent}
        if self.settings.elsevier_insttoken:
            headers["X-ELS-Insttoken"] = self.settings.elsevier_insttoken
        return self._get(f"https://api.elsevier.com/content/article/doi/{quote(doi, safe='/')}", headers)

    def wiley(self, doi: str) -> tuple[bytes | None, str]:
        if not self.settings.wiley_tdm_token:
            return None, "missing_WILEY_TDM_TOKEN"
        headers = {"Accept": "application/pdf", "Wiley-TDM-Client-Token": self.settings.wiley_tdm_token, "User-Agent": self.user_agent}
        return self._get(f"https://api.wiley.com/onlinelibrary/tdm/v1/articles/{quote(doi, safe='')}", headers)

    def springer(self, doi: str) -> tuple[bytes | None, str]:
        headers = {"Accept": "application/pdf", "User-Agent": self.user_agent}
        if self.settings.springer_api_key:
            try:
                response = self.session.get(
                    "https://api.springernature.com/openaccess/json",
                    params={"q": f"doi:{doi}", "api_key": self.settings.springer_api_key},
                    headers={"User-Agent": self.user_agent},
                    timeout=self.settings.request_timeout_s,
                )
                if response.status_code == 200:
                    for record in (response.json() or {}).get("records") or []:
                        for location in record.get("url") or []:
                            if isinstance(location, dict) and location.get("format", "").lower() == "pdf" and location.get("value"):
                                content, status = self._get(location["value"], headers)
                                if content:
                                    return content, status
            except (requests.RequestException, ValueError):
                pass
        # Springer/BMC DOI content URLs are attempted only after the official OA
        # metadata endpoint and still must return a real PDF.
        return self._get(f"https://link.springer.com/content/pdf/{quote(doi, safe='/')}.pdf", headers)
