---
name: doi2pdf
description: "Fetch and verify academic PDFs from a DOI through lawful, provenance-aware layers: open access indexes and repositories, official publisher TDM APIs, the user's own OpenAthens/EZproxy institutional session, and a manual library resolver fallback. Use when Codex needs to download a paper, diagnose why a DOI has no automatic full text, initialize institutional login, preserve Zotero PDF naming, or report which access route succeeded. Also use for PMID-backed PMC lookups and Zotero translation-server attachment discovery. Never use it to bypass a paywall, solve CAPTCHAs, share credentials, or retrieve from pirate sources."
---

# DOI2PDF

Use the installed `doi2pdf` command as the deterministic implementation. Preserve route
provenance and stop after the first response verified as a PDF. Keep keys and browser cookies
out of prompts, command arguments, logs, and responses.

## Workflow

1. Run `doi2pdf doctor --json`. If the command is unavailable, run
   `python scripts/install_cli.py` relative to this skill directory. Add `--with-browser` only
   when institutional login is required and the user permits installing Chromium.
2. If doctor returns `setup_required`, launch `doi2pdf-web` and direct the user to the local
   HTML console. Use **Settings** for configuration, **Activity** for sanitized live logs, and
   the job progress page for route-by-route monitoring. Never ask the user to paste an API key
   or password into chat.
3. Normalize and verify the DOI; never invent one. If only a title/PMID is available, resolve
   it through a trustworthy metadata service before fetching.
4. Prefer `doi2pdf fetch <DOI> --no-institution --json` first. Parse the JSON
   envelope; do not scrape human logs.
5. If OA/TDM routes fail and the user has legitimate subscription access, check that their
   own OpenAthens or EZproxy prefix is configured. Run `doi2pdf login --json` when an
   interactive SSO/MFA session is needed, then retry without `--no-institution`.
6. If all automatic routes fail, return `resolver_url` for manual completion. Do not add an
   unauthorized fallback.
7. Report the winning `layer`, `route`, output path, byte count, hash, and relevant failed
   route statuses. Never expose keys, cookies, headers, or credentials.

For nontechnical local use, launch `DOI2PDF.bat`. Complete `/setup` on first run, retrieve
from the Fetch page, follow the live progress tracker, then use the tokenized **Open PDF** or
**Download a copy** button. Use `/activity` to monitor recent jobs. Logs are in memory only,
reset on restart, and must never include keys, cookies, request headers, or signed URLs. If the
CLI succeeds but the website appears not to provide a file, verify the result page contains
`/files/<token>` and check `/health`; never expose a raw user-supplied filesystem path.

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
doi2pdf doctor --json
doi2pdf resolve "https://doi.org/10.1186/s12984-023-01168-x" --json
doi2pdf fetch 10.1186/s12984-023-01168-x --no-institution --json
doi2pdf login --json
doi2pdf fetch 10.1002/example --zotero-key 9ET75JMH --author Chen --year 2026 --json
doi2pdf batch-zotero --db "$HOME\Zotero\zotero.sqlite" --limit 10 --json
```

Treat exit `2` as invalid input/setup, `3` as no automatic PDF/manual completion, `4` as
human login required, and `5` as an unexpected runtime failure. Always inspect `status` and
`resolver_url` in the JSON envelope before deciding the next action.

Read [references/configuration.md](references/configuration.md) when configuring API keys,
Zotero translation-server, OpenAthens, EZproxy, or resolver templates.
