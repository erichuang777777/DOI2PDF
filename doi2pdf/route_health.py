"""Sanitized access-log summaries for institutional route health."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .publisher_routes import ROUTES


def read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
            if isinstance(event, dict):
                events.append(event)
        except ValueError:
            continue
    return events


def summary(path: Path) -> dict[str, Any]:
    events = read_events(path)
    routes = [event for event in events if event.get("kind") == "route"]
    statuses = Counter(event.get("status", "unknown") for event in routes)
    blocks = sum(statuses[name] for name in ("cf_block", "cf_challenge", "rate_limited"))
    scorecard = []
    for prefix, spec in sorted(ROUTES.items()):
        rows = [event for event in routes if event.get("prefix") == prefix]
        counts = Counter(event.get("status", "unknown") for event in rows)
        pdf = sum(count for status, count in counts.items() if str(status).startswith("pdf"))
        scorecard.append({"prefix": prefix, "kind": spec.kind, "label": spec.label, "pdf": pdf, "failures": sum(counts.values()) - pdf, "statuses": dict(counts)})
    gaps = sorted({event["prefix"] for event in routes if event.get("subscribed") is True and event.get("prefix") not in ROUTES})
    return {"events": len(events), "route_events": len(routes), "statuses": dict(statuses), "blocks": blocks, "routes": scorecard, "subscribed_route_gaps": gaps}
