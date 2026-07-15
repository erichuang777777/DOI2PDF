"""Sanitized publisher PDF selectors learned only after validated downloads."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


_UNSAFE = re.compile(r"https?://|[?&](?:token|sig|key|auth|session)=|cookie|password", re.I)


def _host(value: str) -> str:
    raw = urlsplit(value).hostname if "://" in value else value
    host = (raw or "").lower().strip(".")
    if not host or not re.fullmatch(r"[a-z0-9.-]+", host):
        raise ValueError("A valid publisher hostname is required.")
    return host


def _selector(value: str) -> str:
    selector = re.sub(r"\s+", " ", str(value)).strip()[:500]
    if not selector or _UNSAFE.search(selector):
        raise ValueError("Learned selectors cannot contain URLs, credentials, or signed query data.")
    return selector


def _count(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


class RuleStore:
    def __init__(self, path: Path):
        self.path = path

    def _read(self) -> list[dict[str, Any]]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return []
        raw_rules = value.get("rules", []) if isinstance(value, dict) and isinstance(value.get("rules"), list) else []
        rules = []
        for raw in raw_rules:
            if not isinstance(raw, dict):
                continue
            try:
                hostname, selector = _host(str(raw.get("host", ""))), _selector(str(raw.get("selector", "")))
            except ValueError:
                continue
            hint = re.sub(r"\s+", " ", str(raw.get("text_hint", ""))).strip()[:120]
            rules.append({
                "host": hostname, "selector": selector, "text_hint": "" if _UNSAFE.search(hint) else hint,
                "source": raw.get("source") if raw.get("source") in {"learned", "llm", "deterministic"} else "learned",
                "successes": _count(raw.get("successes", 0)), "failures": _count(raw.get("failures", 0)),
                "consecutive_failures": _count(raw.get("consecutive_failures", 0)),
                "enabled": bool(raw.get("enabled", True)),
                "status": raw.get("status") if raw.get("status") in {"provisional", "verified", "disabled"} else "provisional",
                **{key: int(raw[key]) for key in ("created_at", "last_success_at", "last_failure_at") if isinstance(raw.get(key), (int, float))},
            })
        return rules

    def _write(self, rules: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"schema": 1, "rules": rules}, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def list(self, host: str | None = None) -> list[dict[str, Any]]:
        wanted = _host(host) if host else None
        rules = [row for row in self._read() if not wanted or row.get("host") == wanted]
        return sorted(rules, key=lambda row: (-int(row.get("successes", 0)), int(row.get("failures", 0)), str(row.get("host", ""))))

    def remember(self, host: str, selector: str, *, text_hint: str = "", source: str = "deterministic") -> dict[str, Any]:
        hostname, stable = _host(host), _selector(selector)
        rules = self._read()
        now = int(time.time())
        row = next((item for item in rules if item.get("host") == hostname and item.get("selector") == stable), None)
        if row is None:
            hint = re.sub(r"\s+", " ", text_hint).strip()[:120]
            row = {"host": hostname, "selector": stable, "text_hint": "" if _UNSAFE.search(hint) else hint,
                   "source": source if source in {"learned", "llm", "deterministic"} else "learned",
                   "successes": 0, "failures": 0, "consecutive_failures": 0, "enabled": True,
                   "status": "provisional", "created_at": now}
            rules.append(row)
        row.update({"successes": int(row.get("successes", 0)) + 1, "consecutive_failures": 0,
                    "enabled": True, "status": "verified" if int(row.get("successes", 0)) + 1 >= 2 else "provisional",
                    "last_success_at": now})
        self._write(rules)
        return dict(row)

    def failed(self, host: str, selector: str) -> None:
        hostname, stable = _host(host), _selector(selector)
        rules = self._read()
        row = next((item for item in rules if item.get("host") == hostname and item.get("selector") == stable), None)
        if row is None:
            return
        consecutive = int(row.get("consecutive_failures", 0)) + 1
        row.update({"failures": int(row.get("failures", 0)) + 1, "consecutive_failures": consecutive,
                    "last_failure_at": int(time.time())})
        if consecutive >= 3:
            row.update({"enabled": False, "status": "disabled"})
        self._write(rules)

    def forget(self, host: str) -> int:
        hostname = _host(host)
        rules = self._read()
        kept = [row for row in rules if row.get("host") != hostname]
        removed = len(rules) - len(kept)
        if removed:
            self._write(kept)
        return removed
