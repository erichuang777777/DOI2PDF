from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit


DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
TRAILING = ".,;:)]}>\"'"


def normalize_doi(value: str) -> str:
    raw = unquote(value.strip())
    if raw.lower().startswith("doi:"):
        raw = raw[4:].strip()
    if "://" in raw:
        parsed = urlsplit(raw)
        raw = parsed.path.lstrip("/") if parsed.netloc.lower() in {"doi.org", "dx.doi.org"} else raw
    match = DOI_RE.search(raw)
    if not match:
        raise ValueError(f"No valid DOI found in: {value!r}")
    return match.group(0).rstrip(TRAILING).lower()
