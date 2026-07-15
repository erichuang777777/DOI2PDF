from __future__ import annotations

import sqlite3
import xml.etree.ElementTree as ET
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
        data = self.http.get_json("https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/", params=params)
        result: list[Candidate] = []
        for record in data.get("records") or []:
            if record.get("pmcid"):
                pmcid = record["pmcid"].upper()
                result.append(Candidate(f"https://europepmc.org/articles/{pmcid}?pdf=render", "europe_pmc", "open_access"))
        return result

    def paper_radar(self, doi: str) -> list[Candidate]:
        database = self.settings.paper_radar_db
        if not database or not database.is_file():
            return []
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=5) as connection:
            row = connection.execute("select oa_pdf_url from papers where doi=?", (doi,)).fetchone()
        return [Candidate(row[0], "paper_radar", "open_access", "landing")] if row and row[0] else []

    def arxiv(self, doi: str) -> list[Candidate]:
        low = doi.lower()
        if low.startswith("10.48550/arxiv."):
            return [Candidate(f"https://arxiv.org/pdf/{doi.split('.', 2)[2]}.pdf", "arxiv", "open_access")]
        content = self.http.get_content(
            "https://export.arxiv.org/api/query",
            params={"search_query": f"doi:{doi}", "start": 0, "max_results": 1},
        )
        root = ET.fromstring(content)
        entry = root.find("{http://www.w3.org/2005/Atom}entry")
        if entry is None:
            return []
        for link in entry.findall("{http://www.w3.org/2005/Atom}link"):
            if link.attrib.get("title") == "pdf" and link.attrib.get("href"):
                return [Candidate(link.attrib["href"], "arxiv", "open_access")]
        return []

    def europe_pmc_search(self, doi: str) -> list[Candidate]:
        data = self.http.get_json(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params={"query": f"DOI:{doi}", "format": "json", "resultType": "core"},
        )
        results = ((data.get("resultList") or {}).get("result") or [])
        if not results:
            return []
        record = results[0]
        pmcid = record.get("pmcid")
        full_text_ids = ((record.get("fullTextIdList") or {}).get("fullTextId") or [])
        if pmcid and pmcid in full_text_ids:
            return [Candidate(f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={pmcid}&blobtype=pdf", "europe_pmc_search", "open_access")]
        return []

    def candidates(self, doi: str) -> tuple[list[Candidate], list[tuple[str, str]]]:
        candidates: list[Candidate] = []
        errors: list[tuple[str, str]] = []
        for name, resolver in (
            ("unpaywall", self.unpaywall),
            ("semantic_scholar", self.semantic_scholar),
            ("openalex", self.openalex),
            ("europe_pmc", self.europe_pmc),
            ("europe_pmc_search", self.europe_pmc_search),
            ("arxiv", self.arxiv),
            ("paper_radar", self.paper_radar),
        ):
            try:
                candidates.extend(resolver(doi))
            except Exception as exc:
                errors.append((name, f"{exc.__class__.__name__}: {exc}"))
        return _unique(candidates), errors
