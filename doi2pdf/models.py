from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal


Layer = Literal["open_access", "tdm", "institution", "resolver"]


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
        return data
