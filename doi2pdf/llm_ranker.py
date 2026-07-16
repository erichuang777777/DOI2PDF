"""Optional OpenAI-compatible ranking of sanitized PDF-link candidates."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit

import requests

from .config import Settings


def _endpoint(base: str) -> str:
    clean = base.rstrip("/")
    return clean if clean.endswith("/chat/completions") else clean + "/chat/completions"


def _json_object(value: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", value, re.S)
    return json.loads(match.group(0)) if match else {}


def rank(settings: Settings, host: str, candidates: list[dict[str, Any]]) -> int | None:
    if not settings.llm_enabled or not settings.llm_base_url or not settings.llm_model or not candidates:
        return None
    sanitized = []
    for item in candidates[:20]:
        parts = urlsplit(str(item.get("href") or ""))
        sanitized.append({
            "id": int(item["id"]),
            "text": re.sub(r"\s+", " ", str(item.get("text") or "")).strip()[:160],
            "aria": re.sub(r"\s+", " ", str(item.get("aria") or "")).strip()[:120],
            # Never send query strings, fragments, credentials, cookies, or signed URLs.
            "path": parts.path[:300],
        })
    prompt = (
        "Choose the one candidate most likely to be the primary article full-text PDF. "
        "Reject supplements, figures, citations, metrics, and unrelated documents. "
        "Return JSON only as {\"candidate_id\": integer|null, \"reason\": string}."
    )
    headers = {"Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"
    # Bandit B113 is a false positive here; the timeout is explicitly bounded below.
    response = requests.post(  # nosec B113
        _endpoint(settings.llm_base_url), headers=headers,
        json={"model": settings.llm_model, "temperature": 0, "max_tokens": 120,
              "messages": [{"role": "system", "content": prompt},
                           {"role": "user", "content": json.dumps({"publisher_host": host, "candidates": sanitized})}]},
        timeout=max(5, min(60, settings.request_timeout_s)),
    )
    response.raise_for_status()
    data = response.json()
    content = data["choices"][0]["message"]["content"]
    selected = _json_object(content).get("candidate_id")
    valid = {row["id"] for row in sanitized}
    return int(selected) if isinstance(selected, int) and selected in valid else None
