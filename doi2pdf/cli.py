from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .acceptance import corpus
from .api_probe import probe_all
from .config import Settings
from .naming import build_pdf_path
from .pipeline import DOI2PDF
from .zotero import ZoteroLibrary, find_zotero_db


EXIT_OK = 0
EXIT_INPUT_OR_CONFIG = 2
EXIT_NO_PDF = 3
EXIT_LOGIN_REQUIRED = 4
EXIT_RUNTIME_ERROR = 5


def _emit(args, payload: dict, human: str, *, error: bool = False) -> None:
    """Keep machine output on stdout as one JSON envelope."""
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(human, file=sys.stderr if error else sys.stdout)


def _json_argv(argv: list[str] | None) -> list[str] | None:
    """Allow --json before or after the subcommand for agent ergonomics."""
    values = list(sys.argv[1:] if argv is None else argv)
    if "--json" not in values:
        return None if argv is None else values
    return ["--json", *(value for value in values if value != "--json")]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="doi2pdf", description="Fetch papers through lawful OA, TDM, institutional, and resolver layers.")
    parser.add_argument("--json", action="store_true", help="Print one JSON result envelope")
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="Fetch one DOI")
    fetch.add_argument("identifier")
    fetch.add_argument("-o", "--output", type=Path)
    fetch.add_argument("--output-dir", type=Path, default=Path("downloads"))
    fetch.add_argument("--zotero-key")
    fetch.add_argument("--author")
    fetch.add_argument("--year")
    fetch.add_argument("--title")
    fetch.add_argument("--no-institution", action="store_true")
    resolve = sub.add_parser("resolve", help="Normalize a DOI without downloading")
    resolve.add_argument("identifier")
    batch = sub.add_parser("batch-zotero", help="Fetch missing PDFs from a read-only Zotero library scan")
    batch.add_argument("--db", type=Path)
    batch.add_argument("--output-dir", type=Path, default=Path("downloads"))
    batch.add_argument("--limit", type=int)
    batch.add_argument("--no-institution", action="store_true")
    sub.add_parser("login", help="Open the configured institutional login in persistent Chromium")
    sub.add_parser("doctor", help="Check configuration")
    acceptance = sub.add_parser("acceptance", help="List real papers for one-at-a-time access testing")
    acceptance.add_argument("--publisher", help="Filter by publisher name")
    api_check = sub.add_parser("api-check", help="Test configured API credentials against real endpoints")
    api_check.add_argument("--provider", choices=("pubmed", "semantic_scholar", "elsevier", "wiley", "springer"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(_json_argv(argv))
    settings = Settings.from_env()
    app = DOI2PDF(settings)
    if args.command == "acceptance":
        cases = corpus(args.publisher)
        payload = {
            "schema": 1, "ok": True, "command": "acceptance", "status": "ready",
            "checked_without_access": "2026-07-15", "count": len(cases), "cases": cases,
        }
        _emit(args, payload, "\n".join(f"{row['publisher']}: {row['doi']} - {row['title']}" for row in cases))
        return EXIT_OK
    if args.command == "api-check":
        results = probe_all(settings, args.provider)
        configured = [row for row in results if row["configured"]]
        ok = bool(configured) and all(row["ok"] for row in configured)
        status = "ok" if ok else ("no_keys_configured" if not configured else "check_failed")
        payload = {"schema": 1, "ok": ok, "command": "api-check", "status": status, "results": results}
        human = "\n".join(f"{row['provider']}: {row['status']}" for row in results)
        _emit(args, payload, human, error=not ok)
        return EXIT_OK if ok else EXIT_INPUT_OR_CONFIG
    if args.command == "resolve":
        try:
            doi = app.identifiers.resolve(args.identifier)
        except ValueError as exc:
            payload = {"schema": 1, "ok": False, "command": "resolve", "status": "invalid_identifier", "error": str(exc)}
            _emit(args, payload, str(exc), error=True)
            return EXIT_INPUT_OR_CONFIG
        _emit(args, {"schema": 1, "ok": True, "command": "resolve", "doi": doi}, doi)
        return EXIT_OK
    if args.command == "doctor":
        issues = settings.validate()
        ready = not issues
        payload = {
            "schema": 1,
            "ok": ready,
            "command": "doctor",
            "status": "ready" if ready else "setup_required",
            "issues": issues,
            "setup_command": "doi2pdf-web",
            "web_setup_complete": not settings.needs_setup(),
            "routes": {
                "open_access": bool(settings.unpaywall_email),
                "publisher_tdm": bool(settings.elsevier_api_key or settings.wiley_tdm_token or settings.springer_api_key),
                "institution": bool(settings.openathens_redirector_prefix or settings.ezproxy_prefix),
                "resolver": bool(settings.resolver_template),
            },
        }
        _emit(args, payload, "configuration OK" if payload["ok"] else "\n".join(issues or ["Run doi2pdf-web to finish setup."]), error=not payload["ok"])
        return EXIT_OK if payload["ok"] else EXIT_INPUT_OR_CONFIG
    if args.command == "login":
        try:
            app.institution.login()
        except Exception as exc:
            payload = {"schema": 1, "ok": False, "command": "login", "status": "login_required", "error": f"{type(exc).__name__}: {exc}"}
            _emit(args, payload, payload["error"], error=True)
            return EXIT_LOGIN_REQUIRED
        _emit(args, {"schema": 1, "ok": True, "command": "login", "status": "session_ready"}, "Institutional session ready.")
        return EXIT_OK
    if args.command == "batch-zotero":
        db = args.db or find_zotero_db()
        if not db or not db.exists():
            payload = {"schema": 1, "ok": False, "command": "batch-zotero", "status": "zotero_database_missing", "error": "Zotero database not found; pass --db PATH"}
            _emit(args, payload, payload["error"], error=True)
            return EXIT_INPUT_OR_CONFIG
        outcomes = []
        for item in ZoteroLibrary(db).missing_pdfs(args.limit):
            target = build_pdf_path(
                args.output_dir, zotero_key=item["key"], author=item["author"],
                year=item["year"], title=item["title"], doi=item["doi"],
            )
            try:
                result = app.fetch(item["doi"] or item["title"] or "", target, not args.no_institution)
                outcomes.append(result.to_dict())
            except Exception as exc:
                outcomes.append({"schema": 1, "ok": False, "doi": item["doi"], "path": None,
                                 "item_key": item["key"], "error": f"{type(exc).__name__}: {exc}"})
            # Public APIs also deserve a light courtesy pause; the institutional path
            # applies its stronger persistent limiter independently.
            time.sleep(1)
        succeeded = sum(bool(row.get("ok")) for row in outcomes)
        failed = sum(not bool(row.get("ok")) for row in outcomes)
        summary = {"ok": failed == 0, "succeeded": succeeded, "failed": failed, "results": outcomes}
        summary.update({"schema": 1, "command": "batch-zotero", "status": "complete" if not summary["failed"] else "partial_failure"})
        _emit(args, summary, f"Zotero batch complete: {summary['succeeded']} succeeded, {summary['failed']} failed", error=bool(summary["failed"]))
        return EXIT_OK if not summary["failed"] else EXIT_NO_PDF
    try:
        doi = app.identifiers.resolve(args.identifier)
    except ValueError as exc:
        payload = {"schema": 1, "ok": False, "command": "fetch", "status": "invalid_identifier", "error": str(exc)}
        _emit(args, payload, str(exc), error=True)
        return EXIT_INPUT_OR_CONFIG
    provisional = args.output or args.output_dir / f".{doi.replace('/', '_')}.download.pdf"
    try:
        result = app.fetch(doi, provisional, use_institution=not args.no_institution)
    except Exception as exc:
        payload = {"schema": 1, "ok": False, "command": "fetch", "status": "runtime_error", "doi": doi, "error": f"{type(exc).__name__}: {exc}"}
        _emit(args, payload, payload["error"], error=True)
        return EXIT_RUNTIME_ERROR
    if result.ok and not args.output:
        final_path = build_pdf_path(
            args.output_dir,
            zotero_key=args.zotero_key,
            author=args.author,
            year=args.year,
            title=args.title,
            doi=doi,
            metadata=result.metadata.get("zotero") or {},
        )
        provisional.replace(final_path)
        result.path = final_path
    payload = result.to_dict()
    payload.update({"command": "fetch", "status": "pdf_saved" if result.ok else ("manual_required" if result.resolver_url else "no_pdf")})
    if result.ok:
        human = f"PDF saved: {result.path} via {result.layer}/{result.route}"
    else:
        human = "No automatic route produced a PDF."
        if result.resolver_url:
            human += f"\nLibrary resolver: {result.resolver_url}"
    _emit(args, payload, human, error=not result.ok)
    return EXIT_OK if result.ok else EXIT_NO_PDF


if __name__ == "__main__":
    raise SystemExit(main())
