"""Read-only journal entitlement checks using Crossref plus a local holdings DB."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from .config import Settings


SCHEMA = """CREATE TABLE journals (
  title TEXT, publisher TEXT, issn_print TEXT, issn_e TEXT,
  is_free INT, coverage TEXT
)"""


def _issn(value: str | None) -> str | None:
    compact = re.sub(r"[^0-9Xx]", "", value or "").upper()
    return f"{compact[:4]}-{compact[4:]}" if len(compact) == 8 else None


def _title(value: str | None) -> str:
    text = (value or "").lower().replace("&", " and ")
    return re.sub(r"^the", "", re.sub(r"[^a-z0-9]", "", text.replace("(core journal)", "")))


def coverage_ok(coverage: str | None, year: int | None) -> bool | None:
    if not coverage or not year:
        return None
    ranges: list[tuple[int, int]] = []
    for chunk in re.split(r"(?=\bfrom\s+\d{4})", coverage, flags=re.I):
        start = re.search(r"from\s+(\d{4})", chunk, re.I)
        if start:
            end = re.search(r"until\s+(\d{4})", chunk, re.I)
            ranges.append((int(start.group(1)), int(end.group(1)) if end else 9999))
    return any(start <= year <= end for start, end in ranges) if ranges else None


class Holdings:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = settings.holdings_db
        self.cache = settings.browser_profile / "doi_metadata_cache.json"

    @property
    def configured(self) -> bool:
        return bool(self.db and self.db.is_file())

    def doi_metadata(self, doi: str) -> dict[str, Any]:
        try:
            cache = json.loads(self.cache.read_text(encoding="utf-8")) if self.cache.exists() else {}
        except (OSError, ValueError):
            cache = {}
        if doi in cache:
            return cache[doi]
        metadata: dict[str, Any] = {"issns": [], "journal": "", "year": None}
        response = requests.get(
            f"https://api.crossref.org/works/{quote(doi, safe='/')}",
            headers={"User-Agent": f"DOI2PDF holdings (mailto:{self.settings.contact_email})"},
            timeout=max(5, self.settings.request_timeout_s),
        )
        if response.status_code == 200:
            message = (response.json() or {}).get("message") or {}
            metadata["issns"] = list(dict.fromkeys(value for raw in (message.get("ISSN") or []) if (value := _issn(raw))))
            containers = message.get("container-title") or []
            metadata["journal"] = containers[0] if containers else ""
            for key in ("published", "issued", "published-online", "published-print"):
                parts = ((message.get(key) or {}).get("date-parts") or [[None]])[0]
                if parts and parts[0]:
                    metadata["year"] = int(parts[0])
                    break
        cache[doi] = metadata
        try:
            self.cache.parent.mkdir(parents=True, exist_ok=True)
            self.cache.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        return metadata

    def check(self, doi: str) -> dict[str, Any]:
        if not self.configured:
            return {"configured": False, "subscribed": None, "covered": None}
        metadata = self.doi_metadata(doi)
        with sqlite3.connect(f"file:{self.db}?mode=ro", uri=True, timeout=5) as connection:
            rows = []
            for issn in metadata["issns"]:
                rows = connection.execute(
                    "select title,publisher,is_free,coverage from journals where issn_print=? or issn_e=?",
                    (issn, issn),
                ).fetchall()
                if rows:
                    break
            if not rows and metadata["journal"]:
                wanted = _title(metadata["journal"])
                rows = [row for row in connection.execute("select title,publisher,is_free,coverage from journals") if _title(row[0]) == wanted]
        if not rows:
            return {"configured": True, "subscribed": None, "covered": None, **metadata}
        title, platform, is_free, coverage = rows[0]
        return {
            "configured": True, "subscribed": not bool(is_free),
            "covered": coverage_ok(coverage, metadata["year"]), "platform": platform,
            "title": title, "coverage": coverage, **metadata,
        }

    def platforms(self) -> list[dict[str, Any]]:
        if not self.configured:
            return []
        with sqlite3.connect(f"file:{self.db}?mode=ro", uri=True, timeout=5) as connection:
            rows = connection.execute(
                "select publisher,count(*) from journals where coalesce(is_free,0)=0 group by publisher order by count(*) desc"
            ).fetchall()
        return [{"platform": platform, "journals": count} for platform, count in rows]
