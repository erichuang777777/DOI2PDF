from __future__ import annotations

from collections import defaultdict
from typing import Any

from .publisher_routes import route_group_for


def batch_group_for(item: dict[str, Any]) -> str:
    doi = str(item.get("doi") or "").strip()
    if doi:
        return route_group_for(doi)
    title = str(item.get("title") or "").strip()
    return f"title:{title[:32].lower()}" if title else "unknown"


def group_items(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[batch_group_for(item)].append(item)
    return dict(grouped)
