from __future__ import annotations

from typing import Any

import requests

from .config import Settings
from .models import Candidate


class ZoteroTranslatorClient:
    """Thin client for Zotero translation-server; the AGPL server stays a separate process."""

    def __init__(self, settings: Settings):
        self.base = settings.translator_url
        self.timeout = settings.request_timeout_s

    def _post(self, endpoint: str, value: str) -> Any:
        response = requests.post(
            f"{self.base}/{endpoint}", data=value.encode("utf-8"),
            headers={"Content-Type": "text/plain", "Accept": "application/json"}, timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def search(self, doi: str) -> list[dict[str, Any]]:
        data = self._post("search", doi)
        return data if isinstance(data, list) else []

    def web(self, url: str) -> list[dict[str, Any]]:
        data = self._post("web", url)
        return data if isinstance(data, list) else []

    @staticmethod
    def attachment_candidates(items: list[dict[str, Any]]) -> list[Candidate]:
        result: list[Candidate] = []
        for item in items:
            for attachment in item.get("attachments") or []:
                url = attachment.get("url")
                mime = (attachment.get("mimeType") or "").lower()
                title = (attachment.get("title") or "").lower()
                if url and ("pdf" in mime or "pdf" in title or url.lower().split("?")[0].endswith(".pdf")):
                    # A translator can run from an institution-authorized network, so an
                    # attachment is not proof of OA. Keep it in the institutional layer.
                    result.append(Candidate(url, "zotero_translator", "institution", metadata={"title": attachment.get("title")}))
        return result
