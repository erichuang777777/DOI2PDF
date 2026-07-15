# DOI2PDF configuration reference

Prefer the HTML page launched by `doi2pdf-web` for first-time configuration. It writes keys
to the local `.env`, loads them into the running process environment, and renders only their
configured state afterward; it never sends a stored key back to the browser.

The local console uses `/` for fetch, `/acceptance` for the real one-at-a-time test corpus,
`/activity` for sanitized in-memory job logs, `/configure` for settings, `/jobs/<id>` for progress, and `/health` for machine-readable
readiness. Progress APIs intentionally omit local paths, secret values, cookies, headers, and
candidate URLs.

## Public metadata and OA

| Variable | Purpose | Required |
|---|---|---|
| `DOI2PDF_CONTACT_EMAIL` | Polite API User-Agent contact | Recommended |
| `UNPAYWALL_EMAIL` | Unpaywall v2 API identity | For Unpaywall |
| `PUBMED_API_KEY` | NCBI id-converter quota | Optional |
| `S2_API_KEY` | Semantic Scholar quota | Optional |
| `DOI2PDF_SETUP_COMPLETE` | First-run web wizard state | Written by UI |
| `DOWNLOAD_DIR` | Default local PDF folder | Optional |
| `PAPER_RADAR_DB` | Read-only `papers(doi, oa_pdf_url)` fallback | Optional |

## Official publisher TDM

| Variable | Route |
|---|---|
| `ELSEVIER_TDM_KEY` | Elsevier Article Retrieval API |
| `ELSEVIER_INSTTOKEN` | Optional Elsevier institutional entitlement |
| `WILEY_TDM_TOKEN` | Wiley TDM API |
| `SPRINGER_API_KEY` | Springer Nature OA metadata API |

Users must register their own keys and comply with publisher terms. Never print their values.

After saving keys, use **Test configured API keys** or `doi2pdf api-check --json`. The probe
sends low-volume real requests and reports only configured state, a stable status, and the
HTTP code. `key_accepted` proves the provider accepted the credential for that request; it
does not promise that every article is licensed. `rejected_or_not_entitled` may require a
publisher account or institutional entitlement check. `rate_limited` means stop and retry
later, not increase concurrency.

## Zotero translators

- `DOI2PDF_TRANSLATOR_ENABLED=true`
- `ZOTERO_TRANSLATION_SERVER=http://127.0.0.1:1969`

Run Zotero's `translation-server` separately. The server is AGPL and stays
process-separated from the Python client.

## Institutional access

- `OPENATHENS_REDIRECTOR_PREFIX`: organization-specific prefix ending in `?url=`.
- `EZPROXY_PREFIX`: the user's library prefix, or a template containing `{url}`/`{doi}`.
- `EZPROXY_SUFFIX`: organization-issued publisher-host suffix; enables all paper-fetch routes.
- `LIBRARY_RESOLVER_TEMPLATE`: SFX/OpenURL string containing `{doi}`.
- `HOLDINGS_DB`: read-only journal holdings SQLite used for entitlement/coverage checks.
- `LIBRARY_LOGIN_URL`, `LIBRARY_USERNAME`, `LIBRARY_PASSWORD`: optional plain-form login.
- `LIBRARY_USER_SELECTOR`, `LIBRARY_PASSWORD_SELECTOR`, `LIBRARY_SUBMIT_SELECTOR`: form CSS.
- `DOI2PDF_BROWSER_PROFILE`: private persistent Chromium directory.
- `DOI2PDF_BROWSER_HEADLESS=false`: retain for SSO/MFA unless explicitly safe to change.
- `DOI2PDF_INSTITUTION_INTERVAL_S`: may increase, but code clamps it to at least 15.
- `DOI2PDF_MAX_INSTITUTION_REQUESTS_PER_DAY`: may decrease, but code clamps it to 1–100.

Do not copy another institution's endpoint. Keep institutional passwords only in the ignored
local environment; never render them or place them in command arguments. Do not automate
CAPTCHA, OpenAthens/Shibboleth SSO, or MFA.
