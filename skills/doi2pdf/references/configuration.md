# DOI2PDF configuration reference

## Public metadata and OA

| Variable | Purpose | Required |
|---|---|---|
| `DOI2PDF_CONTACT_EMAIL` | Polite API User-Agent contact | Recommended |
| `UNPAYWALL_EMAIL` | Unpaywall v2 API identity | For Unpaywall |
| `PUBMED_API_KEY` | NCBI id-converter quota | Optional |
| `S2_API_KEY` | Semantic Scholar quota | Optional |

## Official publisher TDM

| Variable | Route |
|---|---|
| `ELSEVIER_TDM_KEY` | Elsevier Article Retrieval API |
| `ELSEVIER_INSTTOKEN` | Optional Elsevier institutional entitlement |
| `WILEY_TDM_TOKEN` | Wiley TDM API |
| `SPRINGER_API_KEY` | Springer Nature OA metadata API |

Users must register their own keys and comply with publisher terms. Never print their values.

## Zotero translators

- `DOI2PDF_TRANSLATOR_ENABLED=true`
- `ZOTERO_TRANSLATION_SERVER=http://127.0.0.1:1969`

Run the bundled `zoteor_translator/translation-server` separately. The server is AGPL and
stays process-separated from the Python client.

## Institutional access

- `OPENATHENS_REDIRECTOR_PREFIX`: organization-specific prefix ending in `?url=`.
- `EZPROXY_PREFIX`: the user's library prefix, or a template containing `{url}`/`{doi}`.
- `LIBRARY_RESOLVER_TEMPLATE`: SFX/OpenURL string containing `{doi}`.
- `DOI2PDF_BROWSER_PROFILE`: private persistent Chromium directory.
- `DOI2PDF_BROWSER_HEADLESS=false`: retain for SSO/MFA unless explicitly safe to change.
- `DOI2PDF_INSTITUTION_INTERVAL_S`: may increase, but code clamps it to at least 15.
- `DOI2PDF_MAX_INSTITUTION_REQUESTS_PER_DAY`: may decrease, but code clamps it to 1–100.

Do not copy another institution's endpoint. Do not store institutional passwords in config.
