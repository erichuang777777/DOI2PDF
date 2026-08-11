from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .api_probe import probe_all
from .capabilities import browser_capabilities
from .config import Settings
from .holdings import Holdings
from .naming import build_pdf_path
from .pipeline import DOI2PDF
from .publisher_routes import ROUTES
from .route_health import summary as health_summary

mcp = FastMCP(
    "doi2pdf",
    instructions=(
        "Fetch papers only through lawful routes: open-access indexes, official publisher TDM "
        "APIs, the caller's own configured institutional access (OpenAthens/EZproxy), and manual "
        "library resolver links. Never attempts to bypass paywalls, solve CAPTCHAs, or use "
        "another person's credentials. Call check_setup first; if PDFs are not appearing, it "
        "explains what configuration is missing."
    ),
)


def _settings() -> Settings:
    # Reload .env on every call (not just at process start) so edits made in the
    # local web console's Settings page take effect without restarting this server.
    try:
        from dotenv import load_dotenv

        load_dotenv(override=True)
    except ImportError:
        pass
    return Settings.from_env()


@mcp.tool()
async def resolve_identifier(identifier: str) -> dict[str, Any]:
    """Normalize a DOI, DOI URL, or PMID into a canonical DOI without downloading anything."""

    def _run() -> dict[str, Any]:
        app = DOI2PDF(_settings())
        try:
            doi = app.identifiers.resolve(identifier)
        except ValueError as exc:
            return {"ok": False, "status": "invalid_identifier", "error": str(exc)}
        return {"ok": True, "status": "resolved", "doi": doi}

    return await asyncio.to_thread(_run)


@mcp.tool()
async def check_setup() -> dict[str, Any]:
    """Report which lawful retrieval layers are configured and ready (same check as `doi2pdf doctor`)."""

    def _run() -> dict[str, Any]:
        settings = _settings()
        issues = settings.validate()
        configuration_ok = not issues
        ready = configuration_ok and settings.setup_complete
        status = "ready" if ready else ("invalid_configuration" if issues else "setup_required")
        return {
            "ok": ready,
            "status": status,
            "configuration_ok": configuration_ok,
            "issues": issues,
            "web_setup_url": "http://127.0.0.1:8765/setup",
            "web_setup_complete": settings.setup_complete,
            "network_mode": settings.normalized_network_mode(),
            "effective_network_mode": settings.effective_network_mode(),
            "routes": {
                "open_access": True,
                "unpaywall": bool(settings.unpaywall_email),
                "openalex": True,
                "pmc": True,
                "arxiv": True,
                "publisher_tdm": bool(settings.elsevier_api_key or settings.wiley_tdm_token or settings.springer_api_key),
                "institution": settings.allow_institutional_fallback(),
                "resolver": bool(settings.resolver_template),
                "publisher_route_count": len(ROUTES),
                "holdings": bool(settings.holdings_db and settings.holdings_db.is_file()),
                "llm_assisted_discovery": settings.llm_enabled,
                "optional_browser": browser_capabilities(),
            },
        }

    return await asyncio.to_thread(_run)


@mcp.tool()
async def list_publisher_routes() -> dict[str, Any]:
    """List the built-in publisher route registry and sanitized local success/failure counts."""

    def _run() -> dict[str, Any]:
        settings = _settings()
        health = health_summary(settings.browser_profile / "access_log.jsonl")
        registry = [
            {"prefix": prefix, "kind": spec.kind, "label": spec.label, "headful": spec.headful}
            for prefix, spec in sorted(ROUTES.items())
        ]
        return {"ok": True, "status": "ready", "registry": registry, "health": health}

    return await asyncio.to_thread(_run)


@mcp.tool()
async def check_holdings(identifier: str) -> dict[str, Any]:
    """Check the caller's configured library holdings/entitlement database for one DOI. Requires HOLDINGS_DB to be set."""

    def _run() -> dict[str, Any]:
        settings = _settings()
        app = DOI2PDF(settings)
        checker = Holdings(settings)
        if not checker.configured:
            return {"ok": False, "status": "not_configured", "error": "Set HOLDINGS_DB to a readable SQLite database."}
        try:
            doi = app.identifiers.resolve(identifier)
            entitlement = checker.check(doi)
        except (ValueError, OSError, RuntimeError) as exc:
            return {"ok": False, "status": "check_failed", "error": f"{type(exc).__name__}: {exc}"}
        return {
            "ok": True,
            "status": "known" if entitlement.get("subscribed") is not None else "unknown",
            "doi": doi,
            "entitlement": entitlement,
        }

    return await asyncio.to_thread(_run)


@mcp.tool()
async def check_api_keys(provider: str = "") -> dict[str, Any]:
    """Send one small real request to each configured publisher API key to confirm it is valid. Optionally limit to one provider name. Makes live network requests and never returns key values."""

    def _run() -> dict[str, Any]:
        settings = _settings()
        results = probe_all(settings, provider or None)
        configured = [row for row in results if row["configured"]]
        ok = bool(configured) and all(row["ok"] for row in configured)
        status = "ok" if ok else ("no_keys_configured" if not configured else "check_failed")
        return {"ok": ok, "status": status, "results": results}

    return await asyncio.to_thread(_run)


@mcp.tool()
async def fetch_pdf(
    identifier: str,
    output_dir: str = "",
    use_institution: bool = True,
    zotero_key: str = "",
    author: str = "",
    year: str = "",
    title: str = "",
) -> dict[str, Any]:
    """Fetch the PDF for a DOI, DOI URL, or PMID through lawful routes only: open access, then
    official publisher TDM APIs, then (if use_institution) the caller's own configured
    OpenAthens/EZproxy/library access. Never bypasses paywalls, solves CAPTCHAs, or shares
    credentials. Saves the PDF under output_dir (defaults to the configured download folder,
    named `{zotero_key}_{author}_{year}.pdf` when those are given) and returns the full route
    report. If no route succeeds, the response includes a resolver_url the caller's own library
    can use to finish the request manually.
    """

    def _run() -> dict[str, Any]:
        settings = _settings()
        app = DOI2PDF(settings)
        try:
            doi = app.identifiers.resolve(identifier)
        except ValueError as exc:
            return {"ok": False, "status": "invalid_identifier", "error": str(exc)}
        directory = Path(output_dir).expanduser() if output_dir else settings.download_dir
        provisional = directory / f".{doi.replace('/', '_')}.download.pdf"
        try:
            result = app.fetch(doi, provisional, use_institution=use_institution)
        except Exception as exc:
            return {"ok": False, "status": "runtime_error", "doi": doi, "error": type(exc).__name__}
        if result.ok:
            final_path = build_pdf_path(
                directory,
                zotero_key=zotero_key,
                author=author,
                year=year,
                title=title,
                doi=doi,
                metadata=result.metadata.get("zotero") or {},
            )
            provisional.replace(final_path)
            result.path = final_path
        payload = result.to_dict()
        payload["status"] = "pdf_saved" if result.ok else ("manual_required" if result.resolver_url else "no_pdf")
        return payload

    return await asyncio.to_thread(_run)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
