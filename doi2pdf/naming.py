from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def _safe(value: str | None, limit: int = 80) -> str:
    if not value:
        return ""
    value = re.sub(r"[^\w.-]+", "_", value, flags=re.UNICODE).strip("._-")
    return value[:limit]


def _first_author(metadata: dict[str, Any]) -> str | None:
    creators = metadata.get("creators") or []
    for creator in creators:
        if creator.get("creatorType") in (None, "author"):
            return creator.get("lastName") or creator.get("name")
    return None


def _year(metadata: dict[str, Any]) -> str | None:
    match = re.search(r"\b(1[5-9]\d{2}|20\d{2}|21\d{2})\b", str(metadata.get("date") or ""))
    return match.group(0) if match else None


def build_pdf_path(
    directory: Path,
    *,
    zotero_key: str | None = None,
    author: str | None = None,
    year: str | None = None,
    title: str | None = None,
    doi: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Path:
    """Preserve the legacy `{ZoteroKey}_{Author}_{Year}.pdf` naming rule."""
    metadata = metadata or {}
    key = _safe(zotero_key, 8) if zotero_key and len(zotero_key) == 8 else ""
    author = _safe(author or _first_author(metadata), 40)
    year = _safe(year or _year(metadata), 4)
    title = _safe(title or metadata.get("title"), 60)
    fallback = _safe((doi or "paper").replace("/", "_"), 80) or "paper"
    suffix = "_".join(part for part in (author, year) if part) or title or fallback
    stem = "_".join(part for part in (key, suffix) if part)
    candidate = directory / f"{stem}.pdf"
    number = 2
    while candidate.exists():
        candidate = directory / f"{stem}_{number}.pdf"
        number += 1
    return candidate
