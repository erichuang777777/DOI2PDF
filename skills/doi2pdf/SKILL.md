---
name: doi2pdf
description: "Fetch and verify academic PDFs from a DOI through lawful, provenance-aware layers: open access indexes and repositories, official publisher TDM APIs, the user's own OpenAthens/EZproxy institutional session, optional sanitized LLM-assisted Playwright link ranking with learned publisher selectors, and a manual library resolver fallback. Use when Codex needs to download a paper, diagnose why a DOI has no automatic full text, initialize institutional login, inspect or forget learned PDF rules, preserve Zotero PDF naming, or report which access route succeeded. Also use for PMID-backed PMC lookups and Zotero translation-server attachment discovery. Never use it to bypass a paywall, solve CAPTCHAs, share credentials, or retrieve from pirate sources."
---

# DOI2PDF

Use the installed `doi2pdf` command as the deterministic implementation. Preserve route
provenance and stop after the first response verified as a PDF. Keep keys and browser cookies
out of prompts, command arguments, logs, and responses.

## Workflow

1. Run `doi2pdf doctor --json`. If the command is unavailable, run
   `python scripts/install_cli.py` relative to this skill directory. Add `--with-browser` only
   when institutional login is required and the user permits installing browser-use and Chromium.
2. If doctor returns `setup_required`, launch `doi2pdf-web` and direct the user to the local
   HTML console. Use **Settings** for configuration, **Activity** for sanitized live logs, and
   the job progress page for route-by-route monitoring. Never ask the user to paste an API key
   or password into chat.
   Set `DOI2PDF_NETWORK_MODE` to `off_campus` when only OA/OpenAthens/API routes should run,
   or `campus` when institutional fallback and browser-assisted discovery are allowed.
   For `auto`, configure the institution's documented networks in `DOI2PDF_CAMPUS_CIDRS`;
   do not infer campus access merely because an EZproxy setting exists.
   Use **Library Access Assistant** when the user has a library-provided link but does not know
   its OpenAthens/EZproxy prefix. Review the inferred setting before applying it; never guess an
   institution from the user's email or use another library's endpoint.
3. After configuring optional API keys, run `doi2pdf api-check --json`. This performs one
   small request against each configured real API; it is not a mock and never returns key
   values. Treat `not_configured` as optional, `invalid_or_unauthorized` as a credential
   problem, and `rejected_or_not_entitled` as either entitlement or publisher policy.
4. Normalize and verify the DOI; never invent one. If only a title/PMID is available, resolve
   it through a trustworthy metadata service before fetching.
5. Prefer `doi2pdf fetch <DOI> --no-institution --json` first. Parse the JSON
   envelope; do not scrape human logs.
6. If OA/TDM routes fail and the user has legitimate subscription access, check that their
   own access route is configured and the network mode allows it. Off-campus mode permits only
   OpenAthens; campus mode permits direct publisher access and EZproxy. Run `doi2pdf login --json` when an
   interactive SSO/MFA session is needed, then retry without `--no-institution`.
   Run `doi2pdf holdings <DOI> --json` when a holdings DB is configured, and do not confuse
   missing coverage with a broken publisher route. Read
   [references/publisher-routes.md](references/publisher-routes.md) for publisher dispatch,
   LWW/Ovid, entitlement, and route-health diagnostics.
   If a publisher immediately shows a bot-verification interstitial, use
   `doi2pdf browser-assist <URL-or-DOI> --json` to open the exact target in the local browser
   profile and complete the check manually. Do not treat this as a CAPTCHA solver.
7. After ordinary publisher and translator routes, reuse verified publisher selectors. If the
   user enabled LLM ranking, allow it to rank only sanitized Playwright candidates. It does not
   authorize or validate a download. Remember a selector only after `%PDF-` validation; inspect
   it with `doi2pdf rules --json`. Never retain a candidate URL or signed query string.
8. If all automatic routes fail, return `resolver_url` for manual completion. Do not add an
   unauthorized fallback.
9. Report the winning `layer`, `route`, output path, byte count, hash, and relevant failed
   route statuses. For PMC, prefer the current anonymous `pmc_cloud` PDF route; do not revive
   the retired legacy FTP/package paths. Never expose keys, cookies, headers, or credentials.

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
- Use direct translator attachment candidates only in campus mode. Off-campus subscription
  retrieval must go through the configured OpenAthens browser session.

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
- Keep CAPTCHA, OpenAthens/Shibboleth SSO, and MFA interactive. Plain form login may read the
  user's own credentials from the ignored environment, but never from command arguments.
- Treat Ovid E3 as an occupied licence seat and honor the enforced cooldown; never retry it
  as if it were a normal HTTP failure.

## Commands

```powershell
doi2pdf doctor --json
doi2pdf api-check --json
doi2pdf acceptance --json
doi2pdf routes --json
doi2pdf rules --json
doi2pdf library-detect "https://login.yourlibrary.edu/login?url=https://publisher.example/article" --json
doi2pdf holdings 10.1056/NEJMoa2404512 --json
doi2pdf resolve "https://doi.org/10.1186/s12984-023-01168-x" --json
doi2pdf fetch 10.1186/s12984-023-01168-x --no-institution --json
doi2pdf login --json
doi2pdf browser-assist https://www.nejm.org/doi/pdf/10.1056/NEJMoa2600157 --json
doi2pdf fetch 10.1002/example --zotero-key 9ET75JMH --author Chen --year 2026 --json
doi2pdf batch-zotero --db "$HOME\Zotero\zotero.sqlite" --limit 10 --json
doi2pdf batch-zotero --db "$HOME\Zotero\zotero.sqlite" --limit 10 --resume --json
doi2pdf manual-review --output failed_manual_review.html --json
doi2pdf zotero-attach --db "$HOME\Zotero\zotero.sqlite" --log playwright-profile/batch_log.jsonl --json
```

Batch runs write a sanitized profile-local JSONL journal. Use `--resume` to skip all previously
attempted items or add `--retry-failed` to retry failures. For Zotero attachment writes, first
inspect the default dry-run result. Only use `--write --yes` after the user has authorized the
write and Zotero is closed; the command makes a timestamped database backup and creates linked
attachments rather than copying files into Zotero storage.

Batch retrieval is group-aware: items are clustered by publisher/route label, OA/TDM discovery
runs first, OpenAlex is prewarmed per group, and institution fallback is only used for the
remaining failures. OA successes do not enter the institution layer.

Learned publisher rules are profile-local and sanitized. One validated success creates a
`provisional` rule, two promote it to `verified`, and three consecutive failures disable it.
Use `doi2pdf rules --forget HOST --yes --json` only when the user asks to remove that host's
rules. Optional LLM ranking must use HTTPS except for loopback local models; it receives only
hostname, candidate text/ARIA, and URL paths with query strings removed. The deterministic
fallback and PDF validation remain mandatory.

Treat exit `2` as invalid input/setup, `3` as no automatic PDF/manual completion, `4` as
human login required, and `5` as an unexpected runtime failure. Always inspect `status` and
`resolver_url` in the JSON envelope before deciding the next action.

When validating institutional behavior that the agent cannot access itself, use
`doi2pdf acceptance --json` or the console's **Acceptance** page. The corpus contains real,
dated controls from several publishers and offers only one-at-a-time retrieval. Do not turn
it into a bulk downloader. Keep confirmed OA successes, PMC records without a reusable PDF,
and subscription controls distinct.

Read [references/configuration.md](references/configuration.md) when configuring API keys,
LLM ranking, Zotero translation-server, OpenAthens, EZproxy, or resolver templates.
