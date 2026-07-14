from __future__ import annotations

import time
from pathlib import Path

from .config import Settings
from .http import HttpClient, atomic_write_pdf
from .institution import InstitutionalBrowser, ProfileBusy
from .models import Attempt, Candidate, FetchResult
from .normalize import normalize_doi
from .open_access import OpenAccessResolver
from .resolver import IdentifierResolver
from .tdm import TDMResolver
from .translator import ZoteroTranslatorClient


class DOI2PDF:
    def __init__(self, settings: Settings | None = None, http: HttpClient | None = None):
        self.settings = settings or Settings.from_env()
        self.http = http or HttpClient(self.settings.contact_email or self.settings.unpaywall_email, self.settings.request_timeout_s)
        self.oa = OpenAccessResolver(self.settings, self.http)
        self.identifiers = IdentifierResolver(self.settings, self.http)
        self.tdm = TDMResolver(self.settings)
        self.translator = ZoteroTranslatorClient(self.settings)
        self.institution = InstitutionalBrowser(self.settings)

    def fetch(self, identifier: str, output: Path, use_institution: bool = True) -> FetchResult:
        started = time.monotonic()
        doi = self.identifiers.resolve(identifier)
        result = FetchResult(doi=doi, resolver_url=self.settings.resolver_url(doi))

        candidates, errors = self.oa.candidates(doi)
        for source, detail in errors:
            result.attempts.append(Attempt(source, "open_access", None, "query_failed", detail))

        metadata_items = []
        if self.settings.translator_enabled:
            try:
                metadata_items = self.translator.search(doi)
                result.metadata["zotero"] = metadata_items[0] if metadata_items else {}
            except Exception as exc:
                result.attempts.append(Attempt("zotero_translator", "open_access", None, "unavailable", str(exc)))

        if self._try_candidates(candidates, output, result):
            return self._finish(result, started)

        for name, route in self.tdm.routes(doi):
            content, status = route(doi)
            result.attempts.append(Attempt(name, "tdm", None, status))
            if content:
                self._success(result, output, content, name, "tdm")
                return self._finish(result, started)

        # Translators are strongest on the resolved publisher page, after OA/TDM APIs.
        if self.settings.translator_enabled:
            try:
                web_items = self.translator.web(f"https://doi.org/{doi}")
                if not result.metadata.get("zotero") and web_items:
                    result.metadata["zotero"] = web_items[0]
                translator_candidates = self.translator.attachment_candidates(metadata_items + web_items)
                if self._try_candidates(translator_candidates, output, result):
                    return self._finish(result, started)
            except Exception as exc:
                result.attempts.append(Attempt("zotero_translator_web", "open_access", None, "unavailable", str(exc)))

        if use_institution:
            try:
                content, family = self.institution.fetch(doi)
                result.attempts.append(Attempt(family, "institution", None, "pdf" if content else "no_pdf"))
                if content:
                    self._success(result, output, content, family, "institution")
                    return self._finish(result, started)
            except ProfileBusy as exc:
                result.attempts.append(Attempt("institution", "institution", None, "busy", str(exc)))
            except Exception as exc:
                result.attempts.append(Attempt("institution", "institution", None, "failed", str(exc)))

        result.attempts.append(Attempt("library_resolver", "resolver", result.resolver_url, "manual_required"))
        return self._finish(result, started)

    def _try_candidates(self, candidates: list[Candidate], output: Path, result: FetchResult) -> bool:
        seen: set[str] = set()
        for candidate in candidates:
            if not candidate.url or candidate.url in seen:
                continue
            seen.add(candidate.url)
            url = candidate.url
            if candidate.kind == "landing":
                url, status = self.http.landing_pdf_url(candidate.url)
                result.attempts.append(Attempt(candidate.source, candidate.layer, candidate.url, status))
                if not url:
                    continue
            content, status = self.http.fetch_pdf(url, candidate.referer or (candidate.url if candidate.kind == "landing" else None))
            result.attempts.append(Attempt(candidate.source, candidate.layer, url, status))
            if content:
                self._success(result, output, content, candidate.source, candidate.layer)
                return True
        return False

    @staticmethod
    def _success(result: FetchResult, output: Path, content: bytes, route: str, layer):
        result.bytes, result.sha256 = atomic_write_pdf(output, content)
        result.ok = True
        result.path = output
        result.route = route
        result.layer = layer

    @staticmethod
    def _finish(result: FetchResult, started: float) -> FetchResult:
        result.elapsed_s = round(time.monotonic() - started, 3)
        return result
