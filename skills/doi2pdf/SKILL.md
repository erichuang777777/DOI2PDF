---
name: doi2pdf
description: "Fetch and verify academic PDFs from a DOI through lawful, provenance-aware layers: open access indexes and repositories, official publisher TDM APIs, the user's own OpenAthens/EZproxy institutional session, and a manual library resolver fallback. Use when Codex needs to download a paper, diagnose why a DOI has no automatic full text, initialize institutional login, preserve Zotero PDF naming, or report which access route succeeded. Also use for PMID-backed PMC lookups and Zotero translation-server attachment discovery. Never use it to bypass a paywall, solve CAPTCHAs, share credentials, or retrieve from pirate sources."
---

# DOI2PDF

Use the repository's `doi2pdf` package as the deterministic implementation. Preserve route
provenance and stop after the first response verified as a PDF.

## Workflow

1. Locate the repository containing `doi2pdf/cli.py`. Run commands from its root.
2. Normalize and verify the DOI; never invent one. If only a title/PMID is available, resolve
   it through a trustworthy metadata service before fetching.
3. Run `python -m doi2pdf.cli doctor`. Explain missing optional settings only when their
   corresponding layer is needed.
4. Prefer `python -m doi2pdf.cli --json fetch <DOI> --no-institution` first. Parse the JSON
   envelope; do not scrape human logs.
5. If OA/TDM routes fail and the user has legitimate subscription access, check that their
   own OpenAthens or EZproxy prefix is configured. Run `python -m doi2pdf.cli login` when an
   interactive SSO/MFA session is needed, then retry without `--no-institution`.
6. If all automatic routes fail, return `resolver_url` for manual completion. Do not add an
   unauthorized fallback.
7. Report the winning `layer`, `route`, output path, byte count, hash, and relevant failed
   route statuses. Never expose keys, cookies, headers, or credentials.

## Zotero behavior

- Keep Zotero translation-server on loopback as a separate process. DOI2PDF uses `/search`
  for metadata and `/web` for landing-page translator attachments.
- Without `-o`, preserve `{ZoteroKey}_{Author}_{Year}.pdf`. Supply `--zotero-key`,
  `--author`, and `--year` when those values are known; otherwise accept translator metadata
  and collision suffixes.
- Treat translator attachment URLs as candidates, never proof: require `%PDF-` validation.

## Institutional safety

- Use only endpoints supplied for the user's own institution and only the user's own account.
- Keep the persistent Playwright profile serial. A busy profile is retryable, not evidence
  that the paper is unavailable.
- Do not lower or remove the enforced 15-second minimum interval or 100-attempt daily ceiling.
- Keep visible Chromium as the default for OpenAthens SSO/MFA. Enable headless only after the
  user has a valid persisted session and their institution permits it.
- Never place passwords in `.env`; never commit `.env`, `config.yaml`, `*.dpapi`, browser
  profiles, or `access_log.jsonl`.
- Stop on publisher/library warnings or suspected systematic-download blocks.

## Commands

```powershell
python -m doi2pdf.cli doctor
python -m doi2pdf.cli resolve "https://doi.org/10.1186/s12984-023-01168-x"
python -m doi2pdf.cli --json fetch 10.1186/s12984-023-01168-x --no-institution
python -m doi2pdf.cli login
python -m doi2pdf.cli --json fetch 10.1002/example --zotero-key 9ET75JMH --author Chen --year 2026
python -m doi2pdf.cli --json batch-zotero --db "$HOME\Zotero\zotero.sqlite" --limit 10
```

Read [references/configuration.md](references/configuration.md) when configuring API keys,
Zotero translation-server, OpenAthens, EZproxy, or resolver templates.
