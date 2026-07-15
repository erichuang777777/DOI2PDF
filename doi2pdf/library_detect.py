"""Infer safe remote-access settings from a user-supplied library link."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlsplit


def _url_prefix(url: str) -> str | None:
    match = re.search(r"([?&]url=)", url, re.I)
    return url[: match.end()] if match else None


def detect_library_link(value: str) -> dict[str, Any]:
    url = value.strip()
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("Paste a complete HTTPS link supplied by your library.")
    if parts.username or parts.password:
        raise ValueError("Library links containing embedded credentials are not accepted.")
    host = parts.hostname.lower()
    prefix = _url_prefix(url)
    if prefix:
        prefix_query = urlsplit(prefix).query
        if any(key.lower() != "url" for key, _ in parse_qsl(prefix_query, keep_blank_values=True)):
            raise ValueError("The reusable prefix contains extra query parameters. Enter it manually after confirming with your library.")
    if prefix and "openathens" in host:
        return {"kind": "openathens", "label": "OpenAthens redirector", "host": host,
                "updates": {"OPENATHENS_REDIRECTOR_PREFIX": prefix},
                "warning": "Complete SSO/MFA yourself in the visible browser."}
    if prefix and ("/login" in parts.path.lower() or any(term in host for term in ("ezproxy", "proxy", "idm.oclc"))):
        return {"kind": "ezproxy_prefix", "label": "EZproxy starting-point URL", "host": host,
                "updates": {"EZPROXY_PREFIX": prefix},
                "warning": "The destination after url= is discarded; only the reusable prefix is saved."}
    labels = host.split(".")
    marker = next((index for index, label in enumerate(labels[1:], 1)
                   if "ezproxy" in label or label in {"proxy", "libproxy"} or label == "idm"), None)
    if marker is not None and marker < len(labels) - 1:
        suffix = ".".join(labels[marker:])
        return {"kind": "ezproxy_suffix", "label": "EZproxy proxy-by-hostname suffix", "host": host,
                "updates": {"EZPROXY_SUFFIX": suffix},
                "warning": "Confirm this suffix belongs to your institution before applying it."}
    raise ValueError("This does not look like an OpenAthens redirector or EZproxy link. Copy a database/full-text link from your library portal.")
