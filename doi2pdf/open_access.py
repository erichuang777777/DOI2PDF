from __future__ import annotations

from urllib.parse import quote

from .config import Settings
from .http import HttpClient
from .models import Candidate


def _unique(candidates: list[Candidate]) -> list[Candidate]:
    seen: set[str] = set()
    out: list[Candidate] = []
    for candidate in candidates:
        if candidate.url and candidate.url not in seen:
            seen.add(candidate.url)
            out.append(candidate)
    return out


class OpenAccessResolver:
    def __init__(self, settings: Settings, http: HttpClient):
        self.settings = settings
        self.http = http

    def unpaywall(self, doi: str) -> list[Candidate]:
        if not self.settings.unpaywall_email:
            return []
        data = self.http.get_json(
            f"https://api.unpaywall.org/v2/{quote(doi, safe='/')}",
            params={"email": self.settings.unpaywall_email},
        )
        locations = []
        if data.get("best_oa_location"):
            locations.append(data["best_oa_location"])
        locations.extend(data.get("oa_locations") or [])
        candidates: list[Candidate] = []
        for location in locations:
            if location.get("url_for_pdf"):
                candidates.append(Candidate(location["url_for_pdf"], "unpaywall", "open_access"))
            landing = location.get("url_for_landing_page") or location.get("url")
            if landing:
                candidates.append(Candidate(landing, "unpaywall", "open_access", "landing"))
        return _unique(candidates)

    def semantic_scholar(self, doi: str) -> list[Candidate]:
        headers = {}
        if self.settings.semantic_scholar_api_key:
            headers["x-api-key"] = self.settings.semantic_scholar_api_key
        data = self.http.get_json(
            f"https://api.semanticscholar.org/graph/v1/paper/DOI:{quote(doi, safe='')}",
            params={"fields": "title,openAccessPdf"}, headers=headers,
        )
        oa = data.get("openAccessPdf") or {}
        return [Candidate(oa["url"], "semantic_scholar", "open_access")] if oa.get("url") else []

    def openalex(self, doi: str) -> list[Candidate]:
        data = self.http.get_json(f"https://api.openalex.org/works/https://doi.org/{quote(doi, safe='/')}")
        locations = []
        best = data.get("best_oa_location")
        if best:
            locations.append(best)
        # OpenAlex `locations` also contains non-OA holdings. Only take entries it
        # explicitly marks OA; otherwise provenance would be mislabeled.
        locations.extend(location for location in (data.get("locations") or []) if location.get("is_oa") is True)
        candidates: list[Candidate] = []
        for location in locations:
            if location.get("pdf_url"):
                candidates.append(Candidate(location["pdf_url"], "openalex", "open_access"))
            if location.get("landing_page_url"):
                candidates.append(Candidate(location["landing_page_url"], "openalex", "open_access", "landing"))
        return _unique(candidates)

    def europe_pmc(self, doi: str) -> list[Candidate]:
        params = {"ids": doi, "format": "json", "tool": "doi2pdf"}
        if self.settings.contact_email:
            params["email"] = self.settings.contact_email
        if self.settings.pubmed_api_key:
            params["api_key"] = self.settings.pubmed_api_key
        data = self.http.get_json("https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/", params=params)
        result: list[Candidate] = []
        for record in data.get("records") or []:
            if record.get("pmcid"):
                pmcid = record["pmcid"].upper()
                result.append(Candidate(f"https://europepmc.org/articles/{pmcid}?pdf=render", "europe_pmc", "open_access"))
        return result

    def candidates(self, doi: str) -> tuple[list[Candidate], list[tuple[str, str]]]:
        candidates: list[Candidate] = []
        errors: list[tuple[str, str]] = []
        for name, resolver in (
            ("unpaywall", self.unpaywall),
            ("semantic_scholar", self.semantic_scholar),
            ("openalex", self.openalex),
            ("europe_pmc", self.europe_pmc),
        ):
            try:
                candidates.extend(resolver(doi))
            except Exception as exc:
                errors.append((name, f"{exc.__class__.__name__}: {exc}"))
        return _unique(candidates), errors
