"""Sanitized, resumable Zotero batch journal and manual-review report."""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote


def append(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    safe = {
        "schema": 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "item_key": str(row.get("item_key") or "")[:32],
        "doi": str(row.get("doi") or "")[:300],
        "title": str(row.get("title") or "")[:500],
        "status": str(row.get("status") or "")[:80],
        "route": str(row.get("route") or "")[:120],
        "group": str(row.get("group") or "")[:120],
        "path": str(row.get("path") or "")[:1000],
        "error_type": str(row.get("error_type") or "")[:120],
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(safe, ensure_ascii=False) + "\n")


def rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    result = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            result.append(value)
    return result


def attempted_keys(path: Path, *, retry_failed: bool = False) -> set[str]:
    accepted = {"success"} if retry_failed else {"success", "no_pdf", "error"}
    return {str(row.get("item_key")) for row in rows(path) if row.get("status") in accepted and row.get("item_key")}


def successful_entries(path: Path) -> list[dict[str, str]]:
    return [
        {"key": str(row.get("item_key")), "filepath": str(row.get("path"))}
        for row in rows(path)
        if row.get("status") == "success" and row.get("item_key") and row.get("path")
    ]


def write_manual_review(path: Path, output: Path, resolver_template: str = "") -> int:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows(path):
        if row.get("item_key"):
            latest[str(row["item_key"])] = row
    failures = [row for row in latest.values() if row.get("status") in {"no_pdf", "error"}]
    table = []
    for row in failures:
        doi = str(row.get("doi") or "")
        resolver = resolver_template.format(doi=quote(doi, safe="")) if resolver_template and doi else ""
        links = f'<a href="https://doi.org/{html.escape(quote(doi, safe="/"), quote=True)}">DOI</a>' if doi else ""
        if resolver:
            links += f' · <a href="{html.escape(resolver, quote=True)}">Library resolver</a>'
        table.append(
            "<tr>"
            f"<td>{html.escape(str(row.get('item_key') or ''))}</td>"
            f"<td>{html.escape(str(row.get('title') or ''))}</td>"
            f"<td>{html.escape(doi)}</td><td>{html.escape(str(row.get('status') or ''))}</td>"
            f"<td>{links}</td></tr>"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "<!doctype html><html><head><meta charset='utf-8'><title>DOI2PDF manual review</title>"
        "<style>body{font:16px system-ui;margin:2rem}table{border-collapse:collapse;width:100%}"
        "th,td{border-bottom:1px solid #ddd;padding:.6rem;text-align:left}</style></head><body>"
        f"<h1>Manual review</h1><p>{len(failures)} latest failed item(s).</p><table>"
        "<thead><tr><th>Item</th><th>Title</th><th>DOI</th><th>Status</th><th>Links</th></tr></thead>"
        f"<tbody>{''.join(table)}</tbody></table></body></html>",
        encoding="utf-8",
    )
    return len(failures)
