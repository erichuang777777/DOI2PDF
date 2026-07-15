from __future__ import annotations

import sqlite3
import threading
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
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
        self._pmcid_cache: dict[str, str | None] = {}
        self._pmcid_lock = threading.Lock()
        self._openalex_batch_cache: dict[str, list[Candidate]] = {}

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

    @staticmethod
    def _openalex_work_candidates(work: dict) -> list[Candidate]:
        locations = []
        best = work.get("best_oa_location")
        if best:
            locations.append(best)
        # OpenAlex `locations` also contains non-OA holdings. Only take entries it
        # explicitly marks OA; otherwise provenance would be mislabeled.
        locations.extend(location for location in (work.get("locations") or []) if location.get("is_oa") is True)
        candidates: list[Candidate] = []
        for location in locations:
            if location.get("pdf_url"):
                candidates.append(Candidate(location["pdf_url"], "openalex", "open_access"))
            if location.get("landing_page_url"):
                candidates.append(Candidate(location["landing_page_url"], "openalex", "open_access", "landing"))
        return _unique(candidates)

    def openalex(self, doi: str) -> list[Candidate]:
        cached = self._openalex_batch_cache.get(doi.lower())
        if cached is not None:
            return cached
        data = self.http.get_json(f"https://api.openalex.org/works/https://doi.org/{quote(doi, safe='/')}")
        return self._openalex_work_candidates(data)

    def prefetch_openalex_batch(self, dois: list[str], chunk_size: int = 25) -> None:
        """Warm the OpenAlex cache for a whole batch of DOIs up front using
        OpenAlex's filter-based multi-ID endpoint, instead of one request per DOI.

        Only OpenAlex offers a free multi-DOI batch lookup; Unpaywall, Semantic
        Scholar, Crossref, and the other sources here don't, so batch mode still
        queries those one DOI at a time. Call this once before fetching a batch
        (e.g. `batch-zotero`); openalex() then serves cached results instead of
        making its own request for every DOI it already covers.
        """
        unique = [doi.lower() for doi in dict.fromkeys(dois) if doi]
        for start in range(0, len(unique), chunk_size):
            chunk = unique[start:start + chunk_size]
            filter_value = "|".join(quote(doi, safe="") for doi in chunk)
            try:
                data = self.http.get_json(
                    "https://api.openalex.org/works",
                    params={"filter": f"doi:{filter_value}", "per_page": chunk_size},
                )
            except Exception:
                continue  # a failed prefetch just means this chunk falls back to per-DOI queries
            for work in data.get("results") or []:
                raw_doi = (work.get("doi") or "").removeprefix("https://doi.org/").lower()
                if raw_doi:
                    self._openalex_batch_cache[raw_doi] = self._openalex_work_candidates(work)
            for doi in chunk:
                # A DOI absent from the response (e.g. not indexed by OpenAlex)
                # must still be cached as "no candidates" so openalex() doesn't
                # re-query it individually.
                self._openalex_batch_cache.setdefault(doi, [])

    def _pmcid(self, doi: str) -> str | None:
        """Resolve a DOI to a PMCID via NCBI idconv, cached per instance.

        europe_pmc() and pmc_direct() both need this lookup; without the cache
        (and the lock, since candidates() now runs sources concurrently) a single
        fetch could hit idconv twice for no reason.
        """
        with self._pmcid_lock:
            if doi in self._pmcid_cache:
                return self._pmcid_cache[doi]
            params = {"ids": doi, "format": "json", "tool": "doi2pdf"}
            if self.settings.contact_email:
                params["email"] = self.settings.contact_email
            if self.settings.pubmed_api_key:
                params["api_key"] = self.settings.pubmed_api_key
            data = self.http.get_json("https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/", params=params)
            pmcid = None
            for record in data.get("records") or []:
                if record.get("pmcid"):
                    pmcid = record["pmcid"].upper()
                    break
            self._pmcid_cache[doi] = pmcid
            return pmcid

    def europe_pmc(self, doi: str) -> list[Candidate]:
        pmcid = self._pmcid(doi)
        return [Candidate(f"https://europepmc.org/articles/{pmcid}?pdf=render", "europe_pmc", "open_access")] if pmcid else []

    def pmc_direct(self, doi: str) -> list[Candidate]:
        """NCBI's own PMC front end, as a fallback when Europe PMC rendering fails."""
        pmcid = self._pmcid(doi)
        return [Candidate(f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/", "pmc_direct", "open_access")] if pmcid else []

    def crossref_links(self, doi: str) -> list[Candidate]:
        """Crossref publishes direct full-text links for many OA publishers (PLOS, MDPI, Hindawi, ...)."""
        data = self.http.get_json(
            f"https://api.crossref.org/works/{quote(doi, safe='/')}",
            headers={"User-Agent": f"DOI2PDF/0.1 (mailto:{self.settings.contact_email})"} if self.settings.contact_email else {},
        )
        message = data.get("message") or {}
        candidates = [
            Candidate(link["URL"], "crossref", "open_access")
            for link in message.get("link") or []
            if link.get("content-type") == "application/pdf" and link.get("URL")
        ]
        return _unique(candidates)

    def core(self, doi: str) -> list[Candidate]:
        """Optional; requires a free CORE API key (CORE_API_KEY)."""
        if not self.settings.core_api_key:
            return []
        data = self.http.get_json(
            "https://api.core.ac.uk/v3/search/works/",
            params={"q": f'doi:"{doi}"'},
            headers={"Authorization": f"Bearer {self.settings.core_api_key}"},
        )
        candidates = [
            Candidate(result["downloadUrl"], "core", "open_access")
            for result in data.get("results") or []
            if result.get("downloadUrl")
        ]
        return _unique(candidates)

    def doaj(self, doi: str) -> list[Candidate]:
        """DOAJ indexes fully-OA journals and often links straight to the full text."""
        data = self.http.get_json(f"https://doaj.org/api/search/articles/doi%3A{quote(doi, safe='')}")
        candidates: list[Candidate] = []
        for result in data.get("results") or []:
            for link in (result.get("bibjson") or {}).get("link") or []:
                if link.get("type") == "fulltext" and link.get("url"):
                    candidates.append(Candidate(link["url"], "doaj", "open_access"))
        return _unique(candidates)

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
        order = (
            ("unpaywall", self.unpaywall),
            ("semantic_scholar", self.semantic_scholar),
            ("openalex", self.openalex),
            ("crossref_links", self.crossref_links),
            ("europe_pmc", self.europe_pmc),
            ("europe_pmc_search", self.europe_pmc_search),
            ("pmc_direct", self.pmc_direct),
            ("arxiv", self.arxiv),
            ("core", self.core),
            ("doaj", self.doaj),
            ("paper_radar", self.paper_radar),
        )
        # These indexes are independent network round-trips; querying them one at a
        # time meant one slow source (e.g. the arXiv Atom API) delayed every other
        # source behind it. Running them concurrently keeps the wall-clock close to
        # the single slowest source instead of their sum. The *download* priority
        # order below is unaffected: results are merged back in `order`, not in
        # completion order, so _try_candidates still tries Unpaywall before arXiv.
        results: dict[str, list[Candidate]] = {}
        errors: list[tuple[str, str]] = []
        with ThreadPoolExecutor(max_workers=min(8, len(order))) as executor:
            future_to_name = {executor.submit(resolver, doi): name for name, resolver in order}
            for future in as_completed(future_to_name):
                name = future_to_name[future]
                try:
                    results[name] = future.result()
                except Exception as exc:
                    errors.append((name, f"{exc.__class__.__name__}: {exc}"))
        candidates = [candidate for name, _ in order for candidate in results.get(name, [])]
        return _unique(candidates), errors
