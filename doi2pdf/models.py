from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
from typing import Any, Literal


Layer = Literal["open_access", "tdm", "institution", "resolver"]
_URL = re.compile(r"https?://\S+", re.I)


def _safe_detail(value: str | None) -> str | None:
    if not value:
        return None
    return _URL.sub("[redacted-url]", value).replace("\r", " ").replace("\n", " ")[:300]


def _public_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    public: dict[str, Any] = {}
    zotero = metadata.get("zotero")
    if isinstance(zotero, dict):
        public["zotero"] = {
            key: zotero[key]
            for key in ("itemType", "title", "creators", "date", "publicationTitle", "DOI")
            if key in zotero
        }
    entitlement = metadata.get("entitlement")
    if isinstance(entitlement, dict):
        public["entitlement"] = {
            key: value for key, value in entitlement.items()
            if key not in {"url", "target_url", "signed_url", "headers", "cookies"}
        }
    return public


@dataclass(frozen=True)
class Candidate:
    url: str
    source: str
    layer: Layer
    kind: Literal["pdf", "landing"] = "pdf"
    referer: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Attempt:
    source: str
    layer: Layer
    url: str | None
    status: str
    detail: str | None = None


@dataclass
class FetchResult:
    doi: str
    ok: bool = False
    path: Path | None = None
    route: str | None = None
    layer: Layer | None = None
    bytes: int = 0
    sha256: str | None = None
    resolver_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    attempts: list[Attempt] = field(default_factory=list)
    elapsed_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["schema"] = 1
        data["path"] = str(self.path.resolve()) if self.path else None
        data["metadata"] = _public_metadata(self.metadata)
        data["attempts"] = [
            {
                "source": attempt.source,
                "layer": attempt.layer,
                "url": None,
                "status": attempt.status,
                "detail": _safe_detail(attempt.detail),
            }
            for attempt in self.attempts
        ]
        return data
