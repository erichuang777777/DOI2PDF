from __future__ import annotations

import re
from difflib import SequenceMatcher

from .config import Settings
from .http import HttpClient
from .normalize import normalize_doi


PMID_RE = re.compile(r"^(?:pmid\s*:\s*)?(\d{5,10})$", re.I)


class IdentifierResolver:
    def __init__(self, settings: Settings, http: HttpClient):
        self.settings = settings
        self.http = http

    def resolve(self, value: str) -> str:
        try:
            return normalize_doi(value)
        except ValueError:
            pass
        pmid = PMID_RE.match(value.strip())
        if pmid:
            doi = self.from_pubmed(pmid.group(1))
            if doi:
                return doi
            raise ValueError(f"PubMed did not return a DOI for PMID {pmid.group(1)}")
        doi = self.from_title(value)
        if doi:
            return doi
        raise ValueError(f"Could not resolve a trustworthy DOI for: {value!r}")

    def from_pubmed(self, pmid: str) -> str | None:
        params = {"ids": pmid, "format": "json", "tool": "doi2pdf"}
        if self.settings.contact_email:
            params["email"] = self.settings.contact_email
        if self.settings.pubmed_api_key:
            params["api_key"] = self.settings.pubmed_api_key
        data = self.http.get_json("https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/", params=params)
        for record in data.get("records") or []:
            if record.get("doi"):
                return normalize_doi(record["doi"])
        return None

    def from_title(self, title: str) -> str | None:
        data = self.http.get_json(
            "https://api.crossref.org/works",
            params={"query.title": title, "rows": 5, "select": "DOI,title"},
        )
        normalized = " ".join(title.lower().split())
        best: tuple[float, str] | None = None
        for item in (data.get("message") or {}).get("items") or []:
            candidate_title = " ".join(" ".join(item.get("title") or []).lower().split())
            doi = item.get("DOI")
            if not candidate_title or not doi:
                continue
            score = SequenceMatcher(None, normalized, candidate_title).ratio()
            if best is None or score > best[0]:
                best = (score, doi)
        return normalize_doi(best[1]) if best and best[0] >= 0.82 else None
