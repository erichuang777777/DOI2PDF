from __future__ import annotations

import hashlib
import io
import ipaddress
import json
import os
import socket
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from pypdf import PdfReader
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ._version import __version__


PDF_MAGIC = b"%PDF-"
MIN_PDF_BYTES = 1024
MAX_PDF_BYTES = 100 * 1024 * 1024
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
STREAM_CHUNK_BYTES = 1024 * 1024
CHALLENGE_MARKERS = (
    "just a moment",
    "performing security verification",
    "verify you are human",
    "validating you are human",
    "驗證您是人類",
    "正在執行安全驗證",
    "attention required! | cloudflare",
    "cdn-cgi/challenge-platform",
    "challenges.cloudflare.com",
    "cf-chl-",
    "cf-turnstile",
    "g-recaptcha",
    "recaptcha/challengepage",
)


def has_pdf_magic(content: bytes) -> bool:
    """Return whether a byte prefix has a PDF header near its beginning."""
    return content[:1024].lstrip().startswith(PDF_MAGIC)


def pdf_validation_status(content: bytes) -> str:
    """Validate a complete, bounded PDF and return an agent-readable status."""
    if len(content) > MAX_PDF_BYTES:
        return "pdf_too_large"
    if not has_pdf_magic(content):
        return "not_pdf"
    if len(content) < MIN_PDF_BYTES:
        return "pdf_too_small"
    if b"%%EOF" not in content[-8192:]:
        return "pdf_missing_eof"
    try:
        reader = PdfReader(io.BytesIO(content), strict=False)
        if len(reader.pages) < 1:
            return "pdf_no_pages"
    except Exception:
        # This boundary parses untrusted publisher output. Any parser failure is
        # a validation failure, never a reason to crash the retrieval pipeline.
        return "pdf_invalid_structure"
    return "pdf"


def looks_like_pdf(content: bytes) -> bool:
    """Return whether complete content is a structurally readable PDF."""
    return pdf_validation_status(content) == "pdf"


def response_declared_too_large(response, maximum: int = MAX_PDF_BYTES) -> bool:
    headers = getattr(response, "headers", {}) or {}
    value = headers.get("content-length") or headers.get("Content-Length")
    try:
        return value is not None and int(value) > maximum
    except (TypeError, ValueError):
        return False


def read_bounded_response(
    response,
    maximum: int = MAX_PDF_BYTES,
    too_large_status: str = "pdf_too_large",
) -> tuple[bytes | None, str]:
    """Read a requests-style response without allowing an unbounded body."""
    if response_declared_too_large(response, maximum):
        return None, too_large_status
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=STREAM_CHUNK_BYTES):
        if not chunk:
            continue
        total += len(chunk)
        if total > maximum:
            return None, too_large_status
        chunks.append(chunk)
    return b"".join(chunks), "body"


def looks_like_challenge(content: bytes) -> bool:
    sample = content[:8192].decode("utf-8", errors="ignore").lower()
    return looks_like_challenge_text(sample)


def looks_like_challenge_text(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in CHALLENGE_MARKERS)


def _is_public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return not (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast or addr.is_unspecified)


class _PublicHostOnlyAdapter(HTTPAdapter):
    """Refuses to connect to a host that resolves to a private/loopback/internal
    address.

    Candidate and redirect-target URLs originate from external OA indexes
    (Unpaywall, OpenAlex, ...); a compromised or malicious index could otherwise
    redirect a fetch to an internal address. This check runs on every hop (the
    adapter is invoked again for each redirect), not just the initial request.
    """

    def send(self, request, **kwargs):
        host = urlsplit(request.url).hostname
        if host:
            try:
                addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
            except socket.gaierror as exc:
                raise requests.exceptions.ConnectionError(f"could not resolve host: {host}") from exc
            if not addresses or not all(_is_public_ip(ip) for ip in addresses):
                raise requests.exceptions.ConnectionError(f"refusing to connect to a non-public host: {host}")
        return super().send(request, **kwargs)


def build_retry_session(
    max_retries: int = 3,
    block_private_hosts: bool = True,
    session: requests.Session | None = None,
) -> requests.Session:
    """Mount a retrying (and, by default, SSRF-guarded) adapter on a session.

    `block_private_hosts=False` is for targets that are intentionally local by
    design and user-configured, not attacker-influenced — e.g. the Zotero
    translation-server, which the README explicitly directs users to run on
    loopback. That's the same carve-out `Settings.validate()` already makes for
    a loopback LLM ranking endpoint.
    """
    session = session or requests.Session()
    # HttpClient (and everything built on this helper) only ever performs GETs,
    # so retries are always idempotent.
    retry = Retry(
        total=max(0, max_retries),
        backoff_factor=0.5,
        backoff_max=8,
        status_forcelist=(429, 500, 502, 503, 504) if max_retries > 0 else None,
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    adapter_cls = _PublicHostOnlyAdapter if block_private_hosts else HTTPAdapter
    adapter = adapter_cls(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class HttpClient:
    def __init__(
        self,
        contact: str,
        timeout: int = 45,
        session: requests.Session | None = None,
        max_retries: int = 3,
        block_private_hosts: bool = True,
    ):
        self.timeout = timeout
        # Transient 5xx/timeouts previously made a whole layer fail immediately
        # and fall through to the next one, needlessly lowering the success rate.
        self.session = build_retry_session(max_retries, block_private_hosts, session=session)
        suffix = f" (mailto:{contact})" if contact else ""
        self.session.headers.update({"User-Agent": f"DOI2PDF/{__version__}{suffix}"})

    def get_json(self, url: str, **kwargs):
        response = self.session.get(url, timeout=self.timeout, stream=True, **kwargs)
        try:
            response.raise_for_status()
            content, status = read_bounded_response(response, MAX_DOCUMENT_BYTES, "document_too_large")
            if content is None:
                raise ValueError(status)
            return json.loads(content)
        finally:
            response.close()

    def get_content(self, url: str, **kwargs) -> bytes:
        response = self.session.get(url, timeout=self.timeout, stream=True, **kwargs)
        try:
            response.raise_for_status()
            content, status = read_bounded_response(response, MAX_DOCUMENT_BYTES, "document_too_large")
            if content is None:
                raise ValueError(status)
            return content
        finally:
            response.close()

    def fetch_pdf(self, url: str, referer: str | None = None) -> tuple[bytes | None, str]:
        headers = {"Accept": "application/pdf,*/*;q=0.8"}
        if referer:
            headers["Referer"] = referer
        try:
            response = self.session.get(url, headers=headers, timeout=self.timeout, allow_redirects=True, stream=True)
        except requests.RequestException as exc:
            return None, f"request_error:{exc.__class__.__name__}"
        try:
            if response.status_code != 200:
                return None, f"http_{response.status_code}"
            content, status = read_bounded_response(response)
            if content is None:
                return None, status
            if looks_like_challenge(content):
                return None, "cf_challenge"
            status = pdf_validation_status(content)
            return (content, status) if status == "pdf" else (None, status)
        finally:
            response.close()

    def landing_pdf_url(self, url: str) -> tuple[str | None, str]:
        try:
            response = self.session.get(url, timeout=self.timeout, allow_redirects=True, stream=True)
        except requests.RequestException as exc:
            return None, f"request_error:{exc.__class__.__name__}"
        try:
            if response.status_code != 200:
                return None, f"http_{response.status_code}"
            maximum = MAX_PDF_BYTES if "pdf" in response.headers.get("content-type", "").lower() else MAX_DOCUMENT_BYTES
            content, status = read_bounded_response(
                response,
                maximum,
                "pdf_too_large" if maximum == MAX_PDF_BYTES else "document_too_large",
            )
            if content is None:
                return None, status
            if looks_like_challenge(content):
                return None, "cf_challenge"
            pdf_status = pdf_validation_status(content)
            if pdf_status == "pdf":
                return response.url, "pdf"
            if has_pdf_magic(content):
                return None, pdf_status
            try:
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(content, "html.parser")
                meta = soup.find("meta", attrs={"name": lambda v: v and v.lower() == "citation_pdf_url"})
                if meta and meta.get("content"):
                    return urljoin(response.url, meta["content"]), "citation_pdf_url"
            except Exception:
                return None, "no_citation_pdf_url"
            return None, "no_citation_pdf_url"
        finally:
            response.close()


def atomic_write_pdf(path: Path, content: bytes) -> tuple[int, str]:
    status = pdf_validation_status(content)
    if status != "pdf":
        raise ValueError(f"content is not a valid PDF: {status}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(content)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return len(content), hashlib.sha256(content).hexdigest()
