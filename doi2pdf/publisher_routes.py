"""Publisher-specific institutional routes adapted from paper-fetch (MIT)."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit, urlunsplit


@dataclass(frozen=True)
class RouteSpec:
    kind: str
    host: str | None = None
    path: str | None = None
    headful: bool = False
    label: str = "publisher"


ROUTES: dict[str, RouteSpec] = {
    "10.1002": RouteSpec("tpl", "onlinelibrary.wiley.com", "/doi/pdfdirect/{doi}?download=true", label="wiley"),
    "10.1111": RouteSpec("tpl", "onlinelibrary.wiley.com", "/doi/pdfdirect/{doi}?download=true", label="wiley"),
    "10.1007": RouteSpec("tpl", "link.springer.com", "/content/pdf/{doi}.pdf", label="springer"),
    "10.1186": RouteSpec("tpl", "link.springer.com", "/content/pdf/{doi}.pdf", label="bmc"),
    "10.1056": RouteSpec("tpl", "www.nejm.org", "/doi/pdf/{doi}", label="nejm"),
    "10.1177": RouteSpec("tpl", "journals.sagepub.com", "/doi/pdf/{doi}?download=true", label="sage"),
    "10.1080": RouteSpec("tpl", "www.tandfonline.com", "/doi/pdf/{doi}?download=true", label="taylor_francis"),
    "10.2214": RouteSpec("tpl", "www.ajronline.org", "/doi/pdf/{doi}?download=true", label="ajr"),
    "10.1148": RouteSpec("tpl", "pubs.rsna.org", "/doi/pdf/{doi}?download=true", label="rsna"),
    "10.1142": RouteSpec("tpl", "www.worldscientific.com", "/doi/pdf/{doi}?download=true", label="world_scientific"),
    "10.1001": RouteSpec("meta", label="jama"),
    "10.1093": RouteSpec("meta", label="oup"),
    "10.1542": RouteSpec("meta", label="pediatrics"),
    "10.1183": RouteSpec("meta", label="erj"),
    "10.3171": RouteSpec("meta", label="jns"),
    "10.1038": RouteSpec("meta", label="nature"),
    "10.1136": RouteSpec("meta", headful=True, label="bmj"),
    "10.3174": RouteSpec("meta", "www.ajnr.org", headful=True, label="ajnr"),
    "10.2967": RouteSpec("meta", "jnm.snmjournals.org", headful=True, label="jnm"),
    "10.1097": RouteSpec("lww", headful=True, label="lww_ovid"),
    "10.1161": RouteSpec("lww", headful=True, label="lww_ovid"),
    "10.1213": RouteSpec("lww", headful=True, label="lww_ovid"),
    "10.2215": RouteSpec("lww", headful=True, label="lww_ovid"),
}


def route_for(doi: str) -> RouteSpec | None:
    return ROUTES.get(doi.lower().split("/", 1)[0])


def template_url(spec: RouteSpec, doi: str) -> str:
    if not spec.host or not spec.path:
        raise ValueError("Route is not a URL template")
    return f"https://{spec.host}{spec.path.format(doi=doi)}"


def proxy_host(host: str, suffix: str) -> str:
    return f"{host.replace('.', '-')}.{suffix.lstrip('.')}"


def rewrite_for_proxy(url: str, suffix: str) -> str:
    parts = urlsplit(url)
    if not parts.hostname or parts.hostname.endswith(suffix.lstrip(".")):
        return url
    port = f":{parts.port}" if parts.port else ""
    return urlunsplit((parts.scheme or "https", proxy_host(parts.hostname, suffix) + port, parts.path, parts.query, parts.fragment))


def citation_pdf_url(document: str) -> str | None:
    match = re.search(
        r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)',
        document, re.I,
    ) or re.search(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']citation_pdf_url["\']',
        document, re.I,
    )
    return html.unescape(match.group(1)) if match else None


def lww_article_details(document: str, article_url: str) -> tuple[str | None, str | None]:
    number = re.search(r'an=?["\']?\s*(\d{8}-\d{9}-\d{5})', document, re.I)
    number = number or re.search(r'\b(\d{8}-\d{9}-\d{5})\b', document)
    path = urlsplit(article_url).path.strip("/").split("/")
    journal = path[0] if path else None
    return (number.group(1) if number else None, journal)


def lww_signed_pdf_url(viewer_html: str) -> str | None:
    decoded = html.unescape(viewer_html)
    match = re.search(r'"pdfUrl"\s*:\s*"([^"]+)"', decoded)
    return match.group(1).replace(r"\/", "/") if match else None


def ovid_viewer_pdf_url(viewer_url: str | None, document: str = "") -> str | None:
    if viewer_url and "file=" in viewer_url:
        return unquote(viewer_url.split("file=", 1)[1].split("#", 1)[0])
    match = re.search(r'/pdfviewer/[^"\'<> ]*file=([^"\'<>\s]+)', document)
    return unquote(match.group(1)) if match else None
