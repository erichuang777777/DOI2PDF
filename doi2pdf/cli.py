from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .acceptance import corpus
from .api_probe import probe_all
from .batch_journal import append as append_batch_log
from .batch_journal import attempted_keys, successful_entries as successful_log_entries, write_manual_review
from .batch_plan import group_items as group_batch_items
from .browser_assist import _safe_url as safe_browser_url
from .browser_assist import open_url as browser_use_open_url
from .config import Settings
from .capabilities import browser_capabilities
from .holdings import Holdings
from .learned_rules import RuleStore
from .library_detect import detect_library_link
from .naming import build_pdf_path
from .pipeline import DOI2PDF
from .publisher_routes import ROUTES, route_for
from .route_health import summary as health_summary
from .zotero import ZoteroLibrary, find_zotero_db
from .zotero_attach import attach_linked_pdfs, successful_csv_entries


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
    batch.add_argument("--resume", action="store_true", help="Skip items already recorded in the sanitized batch journal")
    batch.add_argument("--retry-failed", action="store_true", help="With --resume, retry prior failures and skip successes only")
    batch.add_argument("--log", type=Path, help="Override the profile-local batch journal path")
    attach = sub.add_parser("zotero-attach", help="Dry-run or write linked PDF attachments into Zotero")
    attach.add_argument("--db", type=Path)
    source = attach.add_mutually_exclusive_group(required=True)
    source.add_argument("--csv", type=Path, help="Import successful entries from a DOI2PDF/legacy run CSV")
    source.add_argument("--file", type=Path, help="One validated PDF to attach")
    source.add_argument("--log", type=Path, help="Import successful entries from a DOI2PDF JSONL batch journal")
    attach.add_argument("--item-key", help="Zotero parent item key (required with --file)")
    attach.add_argument("--write", action="store_true", help="Write after making a timestamped database backup")
    attach.add_argument("--yes", action="store_true", help="Required non-interactive confirmation with --write")
    sub.add_parser("login", help="Open the configured institutional login in persistent Chromium")
    sub.add_parser("doctor", help="Check configuration")
    acceptance = sub.add_parser("acceptance", help="List real papers for one-at-a-time access testing")
    acceptance.add_argument("--publisher", help="Filter by publisher name")
    api_check = sub.add_parser("api-check", help="Test configured API credentials against real endpoints")
    api_check.add_argument("--provider", choices=("llm", "pubmed", "semantic_scholar", "elsevier", "wiley", "springer"))
    holdings = sub.add_parser("holdings", help="Check DOI entitlement against a read-only local holdings database")
    holdings.add_argument("identifier", nargs="?")
    holdings.add_argument("--platforms", action="store_true", help="List subscribed platforms")
    sub.add_parser("routes", help="Show publisher route registry and sanitized route-health counts")
    rules = sub.add_parser("rules", help="List or forget sanitized learned publisher selectors")
    rules.add_argument("--host", help="Filter rules by publisher hostname")
    rules.add_argument("--forget", metavar="HOST", help="Forget every learned selector for one hostname")
    rules.add_argument("--yes", action="store_true", help="Required non-interactive confirmation with --forget")
    browser_assist = sub.add_parser("browser-assist", help="Use an optional external browser-use install for manual verification")
    browser_assist.add_argument("target", help="A DOI, DOI URL, or direct article/PDF URL")
    browser_assist.add_argument("--headless", action="store_true", help="Launch browser-use headless (not recommended for verification)")
    browser_assist.add_argument("--no-wait", action="store_true", help="Do not pause for manual verification")
    library_detect = sub.add_parser("library-detect", help="Infer OpenAthens/EZproxy settings from a library-provided link")
    library_detect.add_argument("url")
    review = sub.add_parser("manual-review", help="Create a local HTML review page for latest batch failures")
    review.add_argument("--log", type=Path, help="Override the profile-local batch journal path")
    review.add_argument("--output", type=Path, default=Path("failed_manual_review.html"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(_json_argv(argv))
    settings = Settings.from_env()
    app = DOI2PDF(settings)
    if args.command == "acceptance":
        cases = corpus(args.publisher)
        payload = {
            "schema": 1, "ok": True, "command": "acceptance", "status": "ready",
            "checked_without_access": "2026-07-16", "count": len(cases), "cases": cases,
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
    if args.command == "holdings":
        checker = Holdings(settings)
        if not checker.configured:
            payload = {"schema": 1, "ok": False, "command": "holdings", "status": "not_configured", "error": "Set HOLDINGS_DB to a readable SQLite database."}
            _emit(args, payload, payload["error"], error=True)
            return EXIT_INPUT_OR_CONFIG
        if args.platforms:
            rows = checker.platforms()
            payload = {"schema": 1, "ok": True, "command": "holdings", "status": "ready", "platforms": rows}
            _emit(args, payload, "\n".join(f"{row['platform']}: {row['journals']}" for row in rows))
            return EXIT_OK
        if not args.identifier:
            payload = {"schema": 1, "ok": False, "command": "holdings", "status": "invalid_identifier", "error": "Provide a DOI or use --platforms."}
            _emit(args, payload, payload["error"], error=True)
            return EXIT_INPUT_OR_CONFIG
        try:
            doi = app.identifiers.resolve(args.identifier)
            entitlement = checker.check(doi)
        except (ValueError, OSError, RuntimeError) as exc:
            payload = {"schema": 1, "ok": False, "command": "holdings", "status": "check_failed", "error": f"{type(exc).__name__}: {exc}"}
            _emit(args, payload, payload["error"], error=True)
            return EXIT_RUNTIME_ERROR
        payload = {"schema": 1, "ok": True, "command": "holdings", "status": "known" if entitlement.get("subscribed") is not None else "unknown", "doi": doi, "entitlement": entitlement}
        _emit(args, payload, json.dumps(entitlement, ensure_ascii=False))
        return EXIT_OK
    if args.command == "routes":
        health = health_summary(settings.browser_profile / "access_log.jsonl")
        registry = [{"prefix": prefix, "kind": spec.kind, "label": spec.label, "headful": spec.headful} for prefix, spec in sorted(ROUTES.items())]
        payload = {"schema": 1, "ok": True, "command": "routes", "status": "ready", "registry": registry, "health": health}
        _emit(args, payload, "\n".join(f"{row['prefix']} {row['kind']} {row['label']}" for row in registry))
        return EXIT_OK
    if args.command == "rules":
        store = RuleStore(settings.browser_profile / "learned_pdf_rules.json")
        if args.forget:
            if not args.yes:
                payload = {"schema": 1, "ok": False, "command": "rules", "status": "confirmation_required", "error": "Re-run with --forget HOST --yes."}
                _emit(args, payload, payload["error"], error=True)
                return EXIT_INPUT_OR_CONFIG
            try:
                removed = store.forget(args.forget)
            except ValueError as exc:
                payload = {"schema": 1, "ok": False, "command": "rules", "status": "invalid_host", "error": str(exc)}
                _emit(args, payload, payload["error"], error=True)
                return EXIT_INPUT_OR_CONFIG
            payload = {"schema": 1, "ok": True, "command": "rules", "status": "forgotten", "host": args.forget.lower(), "removed": removed}
            _emit(args, payload, f"Forgot {removed} rule(s) for {args.forget.lower()}.")
            return EXIT_OK
        try:
            rows = store.list(args.host)
        except ValueError as exc:
            payload = {"schema": 1, "ok": False, "command": "rules", "status": "invalid_host", "error": str(exc)}
            _emit(args, payload, payload["error"], error=True)
            return EXIT_INPUT_OR_CONFIG
        payload = {"schema": 1, "ok": True, "command": "rules", "status": "ready", "count": len(rows), "rules": rows}
        _emit(args, payload, "\n".join(f"{row['host']} {row['status']} {row['selector']}" for row in rows) or "No learned rules.")
        return EXIT_OK
    if args.command == "library-detect":
        try:
            detection = detect_library_link(args.url)
        except ValueError as exc:
            payload = {"schema": 1, "ok": False, "command": "library-detect", "status": "not_recognized", "error": str(exc)}
            _emit(args, payload, payload["error"], error=True)
            return EXIT_INPUT_OR_CONFIG
        payload = {"schema": 1, "ok": True, "command": "library-detect", "status": "detected", **detection}
        _emit(args, payload, f"Detected {detection['label']}: {json.dumps(detection['updates'])}")
        return EXIT_OK
    if args.command == "browser-assist":
        capabilities = browser_capabilities()
        if not capabilities["browser_use"]:
            payload = {
                "schema": 1,
                "ok": False,
                "command": "browser-assist",
                "status": "unavailable",
                "error": "browser-use is not installed in this environment",
                "optional_dependency": "browser-use",
            }
            _emit(args, payload, payload["error"], error=True)
            return EXIT_INPUT_OR_CONFIG
        try:
            target = args.target
            if not target.startswith(("http://", "https://")):
                doi = app.identifiers.resolve(target)
                target = app.institution._route_entry_url(doi, route_for(doi)) or app.institution.access_url(doi)[0] or f"https://doi.org/{doi}"
            parts = urlsplit(target)
            if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
                raise ValueError("Browser assist requires an HTTPS URL without embedded credentials")
            result = asyncio.run(browser_use_open_url(target, settings.browser_profile, headless=args.headless, wait_for_console=not args.no_wait))
        except Exception as exc:
            payload = {"schema": 1, "ok": False, "command": "browser-assist", "status": "assist_failed", "error": type(exc).__name__}
            _emit(args, payload, payload["error"], error=True)
            return EXIT_RUNTIME_ERROR
        payload = {"schema": 1, "ok": True, "command": "browser-assist", "target": safe_browser_url(target), **result}
        payload["status"] = result.get("status", "complete")
        human = f"Browser-assist {payload['status']}: {result['after']['current_url']}"
        _emit(args, payload, human)
        return EXIT_OK
    if args.command == "manual-review":
        log_path = args.log or settings.browser_profile / "batch_log.jsonl"
        count = write_manual_review(log_path, args.output, settings.resolver_template)
        payload = {"schema": 1, "ok": True, "command": "manual-review", "status": "complete", "count": count, "output": str(args.output.resolve()), "log": str(log_path.resolve())}
        _emit(args, payload, f"Manual review page written: {args.output.resolve()} ({count} item(s))")
        return EXIT_OK
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
        configuration_ok = not issues
        setup_complete = settings.setup_complete
        ready = configuration_ok and setup_complete
        status = "ready" if ready else ("invalid_configuration" if issues else "setup_required")
        payload = {
            "schema": 1,
            "ok": ready,
            "command": "doctor",
            "status": status,
            "configuration_ok": configuration_ok,
            "issues": issues,
            "setup_command": "doi2pdf-web",
            "web_setup_complete": setup_complete,
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
        _emit(args, payload, "configuration OK" if ready else "\n".join(issues or ["Run doi2pdf-web to finish setup."]), error=not ready)
        return EXIT_OK if payload["ok"] else EXIT_INPUT_OR_CONFIG
    if args.command == "login":
        try:
            app.institution.login()
        except Exception as exc:
            payload = {"schema": 1, "ok": False, "command": "login", "status": "login_required", "error": type(exc).__name__}
            _emit(args, payload, payload["error"], error=True)
            return EXIT_LOGIN_REQUIRED
        _emit(args, {"schema": 1, "ok": True, "command": "login", "status": "session_ready"}, "Institutional session ready.")
        return EXIT_OK
    if args.command == "zotero-attach":
        db = args.db or find_zotero_db()
        if not db or not db.is_file():
            payload = {"schema": 1, "ok": False, "command": "zotero-attach", "status": "zotero_database_missing", "error": "Zotero database not found; pass --db PATH."}
            _emit(args, payload, payload["error"], error=True)
            return EXIT_INPUT_OR_CONFIG
        if args.file and not args.item_key:
            payload = {"schema": 1, "ok": False, "command": "zotero-attach", "status": "item_key_required", "error": "--item-key is required with --file."}
            _emit(args, payload, payload["error"], error=True)
            return EXIT_INPUT_OR_CONFIG
        if args.write and not args.yes:
            payload = {"schema": 1, "ok": False, "command": "zotero-attach", "status": "confirmation_required", "error": "Re-run with --write --yes after closing Zotero. Dry-run is the default."}
            _emit(args, payload, payload["error"], error=True)
            return EXIT_INPUT_OR_CONFIG
        try:
            if args.csv:
                entries = successful_csv_entries(args.csv)
                for entry in entries:
                    source_path = Path(entry["filepath"]).expanduser()
                    if not source_path.is_absolute():
                        entry["filepath"] = str((args.csv.parent / source_path).resolve())
            elif args.log:
                entries = successful_log_entries(args.log)
            else:
                entries = [{"key": args.item_key, "filepath": str(args.file)}]
            result = attach_linked_pdfs(db, entries, write=args.write)
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            payload = {"schema": 1, "ok": False, "command": "zotero-attach", "status": "attach_failed", "error": f"{type(exc).__name__}: {exc}"}
            _emit(args, payload, payload["error"], error=True)
            return EXIT_RUNTIME_ERROR
        bad = [row for row in result["results"] if row["status"] in {"missing_or_not_pdf", "item_not_found"}]
        status = "dry_run" if not args.write else ("partial_failure" if bad else "complete")
        payload = {"schema": 1, "ok": not bad, "command": "zotero-attach", "status": status, **result}
        human = f"Zotero attachment {status}: {len(result['results'])} item(s); backup={result['backup'] or 'not created'}"
        _emit(args, payload, human, error=bool(bad))
        return EXIT_OK if not bad else EXIT_RUNTIME_ERROR
    if args.command == "batch-zotero":
        db = args.db or find_zotero_db()
        if not db or not db.exists():
            payload = {"schema": 1, "ok": False, "command": "batch-zotero", "status": "zotero_database_missing", "error": "Zotero database not found; pass --db PATH"}
            _emit(args, payload, payload["error"], error=True)
            return EXIT_INPUT_OR_CONFIG
        log_path = args.log or settings.browser_profile / "batch_log.jsonl"
        allow_institution = settings.allow_institutional_fallback() and not args.no_institution
        already_tried = attempted_keys(log_path, retry_failed=args.retry_failed) if args.resume else set()
        items = ZoteroLibrary(db).missing_pdfs(args.limit)
        grouped_items = group_batch_items([item for item in items if item.get("key") not in already_tried])

        def run_group(group_name: str, group_items: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
            group_app = DOI2PDF(settings)
            group_dois = [item["doi"] for item in group_items if item["doi"]]
            if group_dois:
                group_app.oa.prefetch_openalex_batch(group_dois)
            local_results: list[dict[str, Any]] = []
            for item in group_items:
                if item["key"] in already_tried:
                    continue
                target = build_pdf_path(
                    args.output_dir,
                    zotero_key=item["key"],
                    author=item["author"],
                    year=item["year"],
                    title=item["title"],
                    doi=item["doi"],
                )
                try:
                    result = group_app.fetch(item["doi"] or item["title"] or "", target, use_institution=False)
                    local_results.append({
                        "item_key": item["key"],
                        "title": item["title"],
                        "doi": result.doi,
                        "group": group_name,
                        "target": target,
                        "result": result,
                    })
                except Exception as exc:
                    local_results.append({
                        "item_key": item["key"],
                        "title": item["title"],
                        "doi": item["doi"],
                        "group": group_name,
                        "target": target,
                        "result": {"schema": 1, "ok": False, "doi": item["doi"], "path": None, "error": f"{type(exc).__name__}: {exc}"},
                    })
                time.sleep(1)
            return group_name, local_results

        with ThreadPoolExecutor(max_workers=min(4, max(1, len(grouped_items)))) as executor:
            futures = [executor.submit(run_group, group_name, group) for group_name, group in sorted(grouped_items.items())]
            phase1 = []
            for future in futures:
                phase1.extend(future.result()[1])

        outcomes: list[dict[str, Any]] = []
        skipped = sum(1 for item in items if item["key"] in already_tried)
        pending_institution: list[dict[str, Any]] = []
        for row in phase1:
            result = row["result"]
            if isinstance(result, dict):
                outcomes.append(result)
                append_batch_log(log_path, {
                    "item_key": row["item_key"],
                    "doi": row["doi"],
                    "title": row["title"],
                    "group": row["group"],
                    "status": "error",
                    "error_type": result.get("error", "fetch_failed"),
                })
                continue
            if result.ok or not allow_institution:
                outcomes.append(result.to_dict())
                append_batch_log(log_path, {
                    "item_key": row["item_key"],
                    "doi": result.doi,
                    "title": row["title"],
                    "group": row["group"],
                    "status": "success" if result.ok else "no_pdf",
                    "route": result.route,
                    "path": result.path,
                })
            else:
                pending_institution.append(row)

        if allow_institution and pending_institution:
            for row in pending_institution:
                target = row["target"]
                try:
                    result = app.fetch(row["doi"] or row["title"] or "", target, use_institution=True)
                    outcomes.append(result.to_dict())
                    append_batch_log(log_path, {
                        "item_key": row["item_key"],
                        "doi": result.doi,
                        "title": row["title"],
                        "group": row["group"],
                        "status": "success" if result.ok else "no_pdf",
                        "route": result.route,
                        "path": result.path,
                    })
                except Exception as exc:
                    outcomes.append({"schema": 1, "ok": False, "doi": row["doi"], "path": None,
                                     "item_key": row["item_key"], "error": f"{type(exc).__name__}: {exc}"})
                    append_batch_log(log_path, {
                        "item_key": row["item_key"],
                        "doi": row["doi"],
                        "title": row["title"],
                        "group": row["group"],
                        "status": "error",
                        "error_type": type(exc).__name__,
                    })
                time.sleep(1)

        succeeded = sum(bool(row.get("ok")) for row in outcomes)
        failed = sum(not bool(row.get("ok")) for row in outcomes)
        summary = {"ok": failed == 0, "succeeded": succeeded, "failed": failed, "skipped": skipped, "groups": len(grouped_items), "log": str(log_path.resolve()), "results": outcomes}
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
        payload = {"schema": 1, "ok": False, "command": "fetch", "status": "runtime_error", "doi": doi, "error": type(exc).__name__}
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
