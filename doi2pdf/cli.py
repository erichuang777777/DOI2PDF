from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .config import Settings
from .naming import build_pdf_path
from .pipeline import DOI2PDF
from .zotero import ZoteroLibrary, find_zotero_db


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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    app = DOI2PDF(settings)
    if args.command == "resolve":
        try:
            doi = app.identifiers.resolve(args.identifier)
        except ValueError as exc:
            payload = {"ok": False, "error": str(exc)}
            print(json.dumps(payload) if args.json else str(exc), file=sys.stderr)
            return 2
        print(json.dumps({"doi": doi}) if args.json else doi)
        return 0
    if args.command == "doctor":
        issues = settings.validate()
        payload = {"ok": not issues, "issues": issues}
        print(json.dumps(payload) if args.json else ("configuration OK" if not issues else "\n".join(issues)))
        return 0 if not issues else 2
    if args.command == "login":
        app.institution.login()
        return 0
    if args.command == "batch-zotero":
        db = args.db or find_zotero_db()
        if not db or not db.exists():
            print("Zotero database not found; pass --db PATH", file=sys.stderr)
            return 2
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
        summary = {"ok": sum(bool(row.get("ok")) for row in outcomes),
                   "failed": sum(not bool(row.get("ok")) for row in outcomes), "results": outcomes}
        print(json.dumps(summary, ensure_ascii=False) if args.json else
              f"Zotero batch complete: {summary['ok']} succeeded, {summary['failed']} failed")
        return 0 if not summary["failed"] else 2
    try:
        doi = app.identifiers.resolve(args.identifier)
    except ValueError as exc:
        payload = {"ok": False, "error": str(exc)}
        print(json.dumps(payload) if args.json else str(exc), file=sys.stderr)
        return 2
    provisional = args.output or args.output_dir / f".{doi.replace('/', '_')}.download.pdf"
    result = app.fetch(doi, provisional, use_institution=not args.no_institution)
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
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False))
    elif result.ok:
        print(f"PDF saved: {result.path} via {result.layer}/{result.route}")
    else:
        print("No automatic route produced a PDF.", file=sys.stderr)
        if result.resolver_url:
            print(f"Library resolver: {result.resolver_url}")
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
