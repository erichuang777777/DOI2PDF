from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from .config import Settings
from .http import HttpClient, atomic_write_pdf, build_retry_session
from .institution import InstitutionalBrowser, ProfileBusy
from .models import Attempt, Candidate, FetchResult
from .open_access import OpenAccessResolver
from .resolver import IdentifierResolver
from .tdm import TDMResolver
from .translator import ZoteroTranslatorClient


class DOI2PDF:
    def __init__(self, settings: Settings | None = None, http: HttpClient | None = None):
        self.settings = settings or Settings.from_env()
        self.http = http or HttpClient(
            self.settings.contact_email or self.settings.unpaywall_email,
            self.settings.request_timeout_s,
            max_retries=self.settings.http_max_retries,
        )
        self.oa = OpenAccessResolver(self.settings, self.http)
        self.identifiers = IdentifierResolver(self.settings, self.http)
        # Reusing HttpClient's session gives tdm the same connection pool,
        # User-Agent, retry adapter, and SSRF guard as the rest of the pipeline
        # (publisher TDM hosts are fixed, known-good, always-public endpoints).
        self.tdm = TDMResolver(self.settings, session=self.http.session)
        # The translation-server is a separate, user-configured process that the
        # README explicitly directs users to run on loopback — it needs its own
        # retrying session *without* the SSRF guard, not HttpClient's, or every
        # request to it would be refused as a "private host".
        translator_session = build_retry_session(self.settings.http_max_retries, block_private_hosts=False)
        self.translator = ZoteroTranslatorClient(self.settings, session=translator_session)
        self.institution = InstitutionalBrowser(self.settings)

    def fetch(
        self,
        identifier: str,
        output: Path,
        use_institution: bool = True,
        progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> FetchResult:
        started = time.monotonic()
        self._emit(progress, 5, "resolving", "Resolving the paper identifier")
        doi = self.identifiers.resolve(identifier)
        result = FetchResult(doi=doi, resolver_url=self.settings.resolver_url(doi))
        allow_institution = use_institution and self.settings.allow_institutional_fallback()
        allow_direct_translator_attachments = allow_institution and self.settings.effective_network_mode() == "campus"
        self._emit(progress, 10, "resolved", "Identifier resolved", source="doi")

        self._emit(progress, 15, "open_access", "Querying open-access indexes")
        candidates, errors = self.oa.candidates(doi)
        for source, detail in errors:
            result.attempts.append(Attempt(source, "open_access", None, "query_failed", detail))
            self._emit(progress, 20, "open_access", "Index query failed", source=source, status="query_failed")

        metadata_items = []
        if self.settings.translator_enabled:
            self._emit(progress, 25, "metadata", "Checking Zotero translator metadata")
            try:
                metadata_items = self.translator.search(doi)
                result.metadata["zotero"] = metadata_items[0] if metadata_items else {}
            except Exception as exc:
                result.attempts.append(Attempt("zotero_translator", "open_access", None, "unavailable", type(exc).__name__))
                self._emit(progress, 25, "metadata", "Translator metadata unavailable", source="zotero_translator", status="unavailable")

        if self._try_candidates(candidates, output, result, progress, 30, 48):
            self._emit(progress, 100, "complete", "Verified open-access PDF saved", source=result.route, status="pdf_saved")
            return self._finish(result, started)

        self._emit(progress, 50, "tdm", "Checking official publisher TDM APIs")
        for name, route in self.tdm.routes(doi):
            content, status = route(doi)
            result.attempts.append(Attempt(name, "tdm", None, status))
            self._emit(progress, 60, "tdm", "Publisher API checked", source=name, status=status)
            if content:
                self._success(result, output, content, name, "tdm")
                self._emit(progress, 100, "complete", "Verified publisher PDF saved", source=name, status="pdf_saved")
                return self._finish(result, started)

        # Translators are strongest on the resolved publisher page, after OA/TDM APIs.
        if self.settings.translator_enabled and allow_direct_translator_attachments:
            self._emit(progress, 68, "translator", "Checking publisher-page translator attachments")
            try:
                web_items = self.translator.web(f"https://doi.org/{doi}")
                if not result.metadata.get("zotero") and web_items:
                    result.metadata["zotero"] = web_items[0]
                translator_candidates = self.translator.attachment_candidates(metadata_items + web_items)
                if self._try_candidates(translator_candidates, output, result, progress, 70, 78):
                    self._emit(progress, 100, "complete", "Verified translator PDF saved", source=result.route, status="pdf_saved")
                    return self._finish(result, started)
            except Exception as exc:
                result.attempts.append(Attempt("zotero_translator_web", "institution", None, "unavailable", type(exc).__name__))
                self._emit(progress, 78, "translator", "Publisher translator unavailable", source="zotero_translator_web", status="unavailable")

        if allow_institution:
            self._emit(progress, 82, "institution", "Checking the authorized institutional session")
            try:
                institution = self.institution.fetch(doi)
                result.metadata["entitlement"] = institution.entitlement
                result.attempts.append(Attempt(institution.route, "institution", None, institution.status))
                self._emit(progress, 92, "institution", "Institutional route checked", source=institution.route, status=institution.status)
                if institution.content:
                    self._success(result, output, institution.content, institution.route, "institution")
                    self._emit(progress, 100, "complete", "Verified institutional PDF saved", source=institution.route, status="pdf_saved")
                    return self._finish(result, started)
            except ProfileBusy:
                result.attempts.append(Attempt("institution", "institution", None, "busy", "profile_busy"))
                self._emit(progress, 92, "institution", "Institutional browser is busy", source="institution", status="busy")
            except Exception as exc:
                result.attempts.append(Attempt("institution", "institution", None, "failed", type(exc).__name__))
                self._emit(progress, 92, "institution", "Institutional route failed", source="institution", status="failed")

        result.attempts.append(Attempt("library_resolver", "resolver", result.resolver_url, "manual_required"))
        self._emit(progress, 100, "resolver", "Automatic routes exhausted; manual resolver available", source="library_resolver", status="manual_required")
        return self._finish(result, started)

    def _try_candidates(
        self,
        candidates: list[Candidate],
        output: Path,
        result: FetchResult,
        progress: Callable[[dict[str, Any]], None] | None = None,
        start_percent: int = 30,
        end_percent: int = 48,
    ) -> bool:
        seen: set[str] = set()
        total = max(1, len(candidates))
        for index, candidate in enumerate(candidates):
            if not candidate.url or candidate.url in seen:
                continue
            seen.add(candidate.url)
            percent = start_percent + int((end_percent - start_percent) * index / total)
            self._emit(progress, percent, candidate.layer, "Checking PDF candidate", source=candidate.source)
            url = candidate.url
            if candidate.kind == "landing":
                url, status = self.http.landing_pdf_url(candidate.url)
                result.attempts.append(Attempt(candidate.source, candidate.layer, candidate.url, status))
                self._emit(progress, percent, candidate.layer, "Landing page checked", source=candidate.source, status=status)
                if not url:
                    continue
            content, status = self.http.fetch_pdf(url, candidate.referer or (candidate.url if candidate.kind == "landing" else None))
            result.attempts.append(Attempt(candidate.source, candidate.layer, url, status))
            self._emit(progress, min(end_percent, percent + 1), candidate.layer, "PDF candidate checked", source=candidate.source, status=status)
            if content:
                self._success(result, output, content, candidate.source, candidate.layer)
                return True
        return False

    @staticmethod
    def _emit(
        callback: Callable[[dict[str, Any]], None] | None,
        percent: int,
        stage: str,
        message: str,
        *,
        source: str | None = None,
        status: str | None = None,
    ) -> None:
        if callback is None:
            return
        event = {"percent": max(0, min(100, percent)), "stage": stage, "message": message}
        if source:
            event["source"] = source
        if status:
            event["status"] = status
        try:
            callback(event)
        except Exception:
            # Monitoring must never break retrieval.
            pass

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
