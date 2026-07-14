from __future__ import annotations

import hashlib
import os
from pathlib import Path
from urllib.parse import urljoin

import requests


PDF_MAGIC = b"%PDF-"


def looks_like_pdf(content: bytes) -> bool:
    return len(content) >= 1024 and content[:1024].lstrip().startswith(PDF_MAGIC)


class HttpClient:
    def __init__(self, contact: str, timeout: int = 45, session: requests.Session | None = None):
        self.timeout = timeout
        self.session = session or requests.Session()
        suffix = f" (mailto:{contact})" if contact else ""
        self.session.headers.update({"User-Agent": f"DOI2PDF/0.1{suffix}"})

    def get_json(self, url: str, **kwargs):
        response = self.session.get(url, timeout=self.timeout, **kwargs)
        response.raise_for_status()
        return response.json()

    def fetch_pdf(self, url: str, referer: str | None = None) -> tuple[bytes | None, str]:
        headers = {"Accept": "application/pdf,*/*;q=0.8"}
        if referer:
            headers["Referer"] = referer
        try:
            response = self.session.get(url, headers=headers, timeout=self.timeout, allow_redirects=True)
        except requests.RequestException as exc:
            return None, f"request_error:{exc.__class__.__name__}"
        if response.status_code != 200:
            return None, f"http_{response.status_code}"
        if not looks_like_pdf(response.content):
            return None, "not_pdf"
        return response.content, "pdf"

    def landing_pdf_url(self, url: str) -> tuple[str | None, str]:
        try:
            response = self.session.get(url, timeout=self.timeout, allow_redirects=True)
        except requests.RequestException as exc:
            return None, f"request_error:{exc.__class__.__name__}"
        if response.status_code != 200:
            return None, f"http_{response.status_code}"
        if looks_like_pdf(response.content):
            return response.url, "pdf"
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(response.text, "html.parser")
            meta = soup.find("meta", attrs={"name": lambda v: v and v.lower() == "citation_pdf_url"})
            if meta and meta.get("content"):
                return urljoin(response.url, meta["content"]), "citation_pdf_url"
        except Exception:
            return None, "no_citation_pdf_url"
        return None, "no_citation_pdf_url"


def atomic_write_pdf(path: Path, content: bytes) -> tuple[int, str]:
    if not looks_like_pdf(content):
        raise ValueError("content is not a PDF")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(content)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return len(content), hashlib.sha256(content).hexdigest()
