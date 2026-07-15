"""Real, low-volume API credential probes with sanitized results."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

import requests

from .config import Settings


def _status(provider: str, configured: bool, response=None, *, pdf: bool = False, error: str | None = None) -> dict[str, Any]:
    if not configured:
        return {"provider": provider, "configured": False, "ok": False, "status": "not_configured"}
    if error:
        return {"provider": provider, "configured": True, "ok": False, "status": "network_error", "error": error}
    code = int(response.status_code)
    if code == 200:
        return {"provider": provider, "configured": True, "ok": True, "status": "ok_pdf" if pdf else "key_accepted", "http_status": code}
    labels = {401: "invalid_or_unauthorized", 403: "rejected_or_not_entitled", 429: "rate_limited"}
    return {"provider": provider, "configured": True, "ok": False, "status": labels.get(code, "unexpected_http"), "http_status": code}


def _call(provider: str, configured: bool, request: Callable[[], Any], *, expect_pdf: bool = False) -> dict[str, Any]:
    if not configured:
        return _status(provider, False)
    response = None
    try:
        response = request()
        prefix = b""
        if expect_pdf and response.status_code == 200:
            prefix = next(response.iter_content(chunk_size=2048), b"")
        return _status(provider, True, response, pdf=prefix.lstrip().startswith(b"%PDF-"))
    except requests.RequestException as exc:
        return _status(provider, True, error=exc.__class__.__name__)
    finally:
        if response is not None:
            response.close()


def probe_all(settings: Settings, provider: str | None = None) -> list[dict[str, Any]]:
    timeout = max(5, min(30, settings.request_timeout_s))
    user_agent = {"User-Agent": f"DOI2PDF credential check (mailto:{settings.contact_email})"}
    checks: dict[str, tuple[bool, Callable[[], Any], bool]] = {
        "llm": (
            bool(settings.llm_enabled and settings.llm_base_url and settings.llm_model),
            lambda: requests.post(
                settings.llm_base_url.rstrip("/") + ("" if settings.llm_base_url.rstrip("/").endswith("/chat/completions") else "/chat/completions"),
                headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {settings.llm_api_key}"} if settings.llm_api_key else {})},
                json={"model": settings.llm_model, "max_tokens": 1, "messages": [{"role": "user", "content": "Reply OK"}]},
                timeout=timeout, stream=True,
            ), False,
        ),
        "pubmed": (
            bool(settings.pubmed_api_key),
            lambda: requests.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                params={"db": "pubmed", "id": "39080964", "retmode": "json", "api_key": settings.pubmed_api_key},
                headers=user_agent, timeout=timeout, stream=True,
            ), False,
        ),
        "semantic_scholar": (
            bool(settings.semantic_scholar_api_key),
            lambda: requests.get(
                "https://api.semanticscholar.org/graph/v1/paper/DOI:10.1101/2024.06.04.597422",
                params={"fields": "title"}, headers={**user_agent, "x-api-key": settings.semantic_scholar_api_key},
                timeout=timeout, stream=True,
            ), False,
        ),
        "elsevier": (
            bool(settings.elsevier_api_key),
            lambda: requests.get(
                "https://api.elsevier.com/content/article/doi/10.1016/j.ipm.2025.104216",
                headers={**user_agent, "Accept": "application/pdf", "X-ELS-APIKey": settings.elsevier_api_key,
                         **({"X-ELS-Insttoken": settings.elsevier_insttoken} if settings.elsevier_insttoken else {})},
                timeout=timeout, stream=True,
            ), True,
        ),
        "wiley": (
            bool(settings.wiley_tdm_token),
            lambda: requests.get(
                "https://api.wiley.com/onlinelibrary/tdm/v1/articles/10.1111%2Fans.17268",
                headers={**user_agent, "Accept": "application/pdf", "Wiley-TDM-Client-Token": settings.wiley_tdm_token},
                timeout=timeout, stream=True,
            ), True,
        ),
        "springer": (
            bool(settings.springer_api_key),
            lambda: requests.get(
                "https://api.springernature.com/openaccess/json",
                params={"q": "doi:10.1186/s12984-023-01168-x", "api_key": settings.springer_api_key},
                headers=user_agent, timeout=timeout, stream=True,
            ), False,
        ),
    }
    selected = {name: value for name, value in checks.items() if not provider or name == provider.lower()}
    if provider and not selected:
        raise ValueError(f"Unknown API provider: {provider}")

    results: dict[str, dict[str, Any]] = {}
    configured = {name: value for name, value in selected.items() if value[0]}
    for name, value in selected.items():
        if not value[0]:
            results[name] = _status(name, False)
    with ThreadPoolExecutor(max_workers=min(3, max(1, len(configured)))) as executor:
        futures = {name: executor.submit(_call, name, True, request, expect_pdf=expect_pdf)
                   for name, (_, request, expect_pdf) in configured.items()}
        for name, future in futures.items():
            results[name] = future.result()
    return [results[name] for name in selected]
