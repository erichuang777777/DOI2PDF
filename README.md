# DOI2PDF

See [CHANGELOG.md](CHANGELOG.md) for release changes and known access constraints.

DOI2PDF combines Zotero PDF Hunter, the lawful route ladder from paper-fetch, and Zotero
translation-server metadata into one provenance-aware tool.

The audited upstream-to-DOI2PDF function checklist is maintained in
[docs/PAPER_FETCH_INTEGRATION.md](docs/PAPER_FETCH_INTEGRATION.md).

It tries, in order:

1. **Open access** — every Unpaywall OA location, Semantic Scholar `openAccessPdf`, every
   OpenAlex location, Crossref `link` full-text entries, the current anonymous PMC AWS
   dataset, PMC→Europe PMC rendering, the direct NCBI PMC front end, arXiv, an optional CORE lookup (needs a free `CORE_API_KEY`),
   DOAJ, and repository `citation_pdf_url`.
2. **Publisher TDM APIs** — Elsevier, Wiley, and Springer using credentials registered by
   the user with those publishers.
3. **Institutional access** — PDF attachments exposed by Zotero translators, then the
   user's own OpenAthens Redirector or EZproxy URL in a persistent Playwright session.
   The default is a visible browser so SSO/MFA can be completed normally; the session is
   reused afterward.
4. **Library resolver** — prints the configured SFX/OpenURL link for manual completion.

Every downloaded response is checked for a real `%PDF-` header and written atomically.
The JSON result records every route and its provenance. OA/TDM requests refuse to connect
to a private, loopback, or link-local address (checked on every redirect hop, not just the
first), since candidate URLs originate from external indexes.

The institutional layer includes the complete paper-fetch v1.0 publisher registry: direct
PDF templates, `citation_pdf_url`, visible human-assisted verification, and the LWW/Ovid signed-URL
plus OCE fallback. A read-only holdings SQLite check distinguishes missing entitlement from
a broken route, while sanitized route-health counters expose blocks and subscribed prefixes
that still lack a route.

## Coding-agent skill

The release asset `doi2pdf-skill.zip` is the primary coding-agent package. It contains the
concise agent workflow, configuration reference, installer, and the matching DOI2PDF wheel.
Extract it into the agent's skills directory, then install its CLI in the agent's Python
environment:

```powershell
python path\to\doi2pdf\scripts\install_cli.py
doi2pdf doctor --json
```

Use `--with-browser` on the installer only when the user needs authorized OpenAthens/EZproxy
access or browser-assisted verification; it installs Playwright and Chromium.
Agents call the global `doi2pdf` command and parse one JSON envelope from stdout.
If setup is required, they launch `doi2pdf-web`; API keys are entered only in the local HTML
page, stored in the ignored `.env`, and never rendered back to the browser or agent.

## Local web console

The local-only console provides five operational views:

- **Fetch** starts a background retrieval without blocking the browser request.
- **Progress** shows the current lawful layer, completion percentage, and sanitized route events.
- **Activity** monitors the latest 50 jobs and updates once per second.
- **Acceptance** offers 5–10 real publisher papers for deliberate, one-at-a-time tests with
  the user's own institutional access; it never launches a bulk run.
- **Settings** manages environment configuration without rendering stored API-key values.
- **Network mode** selects whether DOI2PDF stays on OA/OpenAthens/API only or may fall
  back to institutional browser routes on campus; `auto` compares local interface addresses
  with user-configured campus CIDR ranges.
- Every supported API field links directly to its official registration or access instructions.
- **Library Access Assistant** infers OpenAthens/EZproxy settings from one link copied from the
  user's own library portal, then opens visible login without a terminal prompt.
- **Routes** displays all 23 publisher prefixes and sanitized local success/failure counts.
- **Learned rules** shows publisher selectors learned only after a validated PDF download and
  lets the user forget a host without exposing signed URLs or session data.

Activity logs stay in memory and reset when the server restarts. They omit candidate URLs,
request headers, cookies, local output paths, and API keys. At most two web retrieval jobs run
concurrently; institutional requests retain their separate persistent rate limits.

## One-click Windows app

Double-click **`DOI2PDF.bat`**. On the first run it creates an isolated environment,
installs the lightweight DOI2PDF core and web console, copies the local settings template, starts the server on
`127.0.0.1`, and opens a guided browser setup. Enter a real contact email, choose the PDF
folder, and optionally add your own library access links or publisher API keys. Later starts
reuse the installation and go directly to retrieval.

OA, publisher APIs, resolvers, Zotero integration, and the console do not require a bundled
browser. Only run **`DOI2PDF-browser-setup.bat`** when authorized OpenAthens/EZproxy access
or visible publisher verification is needed; it installs Playwright and Chromium on demand.

The interface accepts a DOI, DOI URL, PMID, or exact title and shows the complete route
report. After success, use **Open PDF** to view it in the browser or **Download a copy** to
use the browser's normal download workflow. Its Settings page stores API keys and
institutional link prefixes only in the Git-ignored local `.env`; it never asks for or
stores an OpenAthens password.

## Red lines

- For people who already have legitimate subscription access. DOI2PDF automates your own
  authenticated session; it is not a way around a paywall or to share an account.
- Your account, your responsibility. Use your own credentials and follow your library's
  license terms and each publisher's terms of service.
- Do not remove the rate limit to bulk-download. Publishers can respond to systematic
  downloading by blocking the institution's whole IP range—your colleagues pay for it.
- Never commit `.env`, `config.yaml`, `*.dpapi`, or `access_log.jsonl`; they are ignored.
- No Sci-Hub, Anna's Archive, CAPTCHA solving, credential sharing, or final access-control
  bypass route is included.

The institutional layer enforces one browser process per profile, at least 15 seconds
between attempts, and at most 100 attempts per local day. Events are written to the local
profile's `access_log.jsonl` without credentials or cookies.

## Install

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
Copy-Item .env.example .env
```

For authorized institutional browser access, install it separately with
`pip install -e ".[browser]"` followed by `playwright install chromium`.

Fill in your email, and only the API keys/library endpoints you actually use. Do not put
OpenAthens passwords in `.env`; login happens in the browser and cookies remain in the
local Playwright profile.

## Usage

```powershell
# Validate configuration (machine-readable flag works before or after the command)
doi2pdf doctor --json

# Send low-volume real requests to configured APIs; no mock response and no key output
doi2pdf api-check --json

# List the curated real-paper acceptance set, optionally filtered by publisher
doi2pdf acceptance --json
doi2pdf acceptance --publisher Elsevier --json

# Inspect the full publisher registry and sanitized route-health scorecard
doi2pdf routes --json
doi2pdf rules --json
doi2pdf library-detect "https://login.yourlibrary.edu/login?url=https://publisher.example/article" --json

# Check article coverage or list subscribed platforms from HOLDINGS_DB
doi2pdf holdings 10.1056/NEJMoa2404512 --json
doi2pdf holdings --platforms --json

# OA/TDM only
doi2pdf --json fetch 10.1186/s12984-023-01168-x --no-institution

# Create/reuse the user's institutional session
doi2pdf login

# Full ladder
doi2pdf --json fetch https://doi.org/10.1002/example -o downloads\paper.pdf

# PMID or exact title is resolved through NCBI/Crossref before the same ladder
doi2pdf resolve "PMID:12345678"

# Read-only Zotero scan; downloads missing PDFs with the legacy filename rule
doi2pdf --json batch-zotero --db "$HOME\Zotero\zotero.sqlite" --limit 10

# Resume a batch, make a local failure review page, then dry-run attachment import
doi2pdf --json batch-zotero --db "$HOME\Zotero\zotero.sqlite" --limit 10 --resume
doi2pdf --json manual-review --output failed_manual_review.html
doi2pdf --json zotero-attach --db "$HOME\Zotero\zotero.sqlite" --log playwright-profile/batch_log.jsonl

# Only after reviewing the dry run and closing Zotero
doi2pdf --json zotero-attach --db "$HOME\Zotero\zotero.sqlite" --log playwright-profile/batch_log.jsonl --write --yes
```

Every batch writes a sanitized, resumable JSONL journal inside the ignored browser profile.
`--resume` skips prior successes and failures; add `--retry-failed` to retry failures while
still skipping successes. `manual-review` converts the latest failures into a local HTML page.
`batch-zotero` now groups items by publisher/route label so different targets can run in
parallel while the same publisher stays serial. It does an OA/TDM-first pass with
OpenAlex prefetching per group, then only sends the remaining failures to institutional
access if you allow it. OA hits skip the institution layer entirely.
`zotero-attach` is dry-run by default, requires explicit `--write --yes`, refuses to write
while Zotero is running, validates the PDF header, and creates a timestamped database backup.

## LLM-assisted final-link discovery

An optional final institutional step can ask an OpenAI-compatible model to rank sanitized
PDF-link candidates found by Playwright. Enable it in **Settings** or configure
`DOI2PDF_LLM_ENABLED`, `DOI2PDF_LLM_BASE_URL`, `DOI2PDF_LLM_MODEL`, and optionally
`DOI2PDF_LLM_API_KEY`. Remote endpoints must use HTTPS; loopback HTTP is allowed for a local
model. `doi2pdf api-check --provider llm --json` tests the configured endpoint.

The model receives only publisher hostname, button/link text, ARIA label, and URL path. Query
strings, page HTML, DOI, cookies, credentials, headers, and signed URLs are not sent. The model
can rank a candidate but cannot declare success: DOI2PDF downloads it through the authorized
session and requires `%PDF-` validation. Only then is its reusable selector written to the
profile-local `learned_pdf_rules.json`. A rule is provisional after one success, verified after
two, and automatically disabled after three consecutive failures. Inspect or remove rules with
`doi2pdf rules --json` or the console's **Learned rules** page.

## Live acceptance testing

The acceptance set is a small dated corpus of real records from Elsevier, Wiley, Nature
Portfolio, NEJM, and Oxford University Press. Each case was attempted from a
machine without subscription access before inclusion. Some are subscription controls; known
OA misses are labeled separately because they diagnose discovery or publisher-route gaps.

Open **Acceptance** in the console and press **Try with my access** for one paper at a time.
The normal progress tracker records which route succeeded. There is intentionally no
"test all" action: institutional rate limits and publisher terms still apply.

Without `-o`, the legacy Zotero naming rule is preserved:
`{ZoteroKey}_{FirstAuthorLastName}_{Year}.pdf`. Explicit values can be supplied:

```powershell
doi2pdf fetch 10.1234/example --zotero-key 9ET75JMH --author Vaswani --year 2017
```

If those flags are absent, DOI2PDF uses Zotero translator metadata, then title/DOI
fallbacks. Existing names are never overwritten; `_2`, `_3`, and so on are appended.

## Zotero translators

Run Zotero's translation-server separately on loopback, then leave
`ZOTERO_TRANSLATION_SERVER=http://127.0.0.1:1969`. DOI2PDF calls `/search` for identifier
metadata and `/web` on the DOI landing page, and treats translator PDF attachments as
candidates. The server remains a separate AGPL process and can be updated independently.

## OpenAthens and EZproxy

For OpenAthens, copy the redirector prefix issued for **your** organization, usually:

```text
https://go.openathens.net/redirector/YOUR-DOMAIN?url=
```

Set it as `OPENATHENS_REDIRECTOR_PREFIX`, run `doi2pdf login`, and complete SSO/MFA in the
visible Chromium window. For EZproxy, set your own library's login prefix or a template
containing `{url}`. DOI2PDF never ships another institution's endpoints.

If you are off campus, keep `DOI2PDF_NETWORK_MODE=off_campus` so DOI2PDF stops after OA,
OpenAthens, and official APIs. On campus, set `DOI2PDF_NETWORK_MODE=campus` to allow the
institutional fallback layer, including direct publisher access, EZproxy, and browser-assisted
discovery. For automatic detection, set `DOI2PDF_NETWORK_MODE=auto` and add your institution's
documented ranges to `DOI2PDF_CAMPUS_CIDRS` (for example `140.112.0.0/16`). If no configured
range matches, Auto behaves as off-campus; merely configuring EZproxy does not prove the machine
is on campus.

If you do not know the prefix, open **Library Access Assistant** in Settings and paste one
database or full-text link copied from your own library portal. It recognizes common
OpenAthens/EZproxy formats, removes the article target, and shows the inferred setting for
approval. **Apply and open login** launches visible Chromium in the background for up to three
minutes, so the web console does not require a terminal prompt. SSO/MFA/CAPTCHA remain manual.

Set `EZPROXY_SUFFIX` when your library uses rewritten publisher hosts such as
`onlinelibrary-wiley-com.<your suffix>`; this enables the original publisher-specific route
registry. Plain EZproxy/NetScaler login forms may optionally use `LIBRARY_LOGIN_URL`,
`LIBRARY_USERNAME`, `LIBRARY_PASSWORD`, and CSS selectors stored only in the ignored `.env`.
OpenAthens/Shibboleth, CAPTCHA, and MFA always remain interactive in visible Chromium.

If a publisher's page immediately drops you into a bot-verification screen, use DOI2PDF's
visible Playwright institutional browser and finish the check manually:

```powershell
doi2pdf login --json
```

This is a pause-for-human-action helper, not a CAPTCHA solver. It keeps the browser visible,
lets you click through the challenge yourself, and then reuses the same profile state on the
next `doi2pdf fetch`.
Playwright and browser-use are optional runtime capabilities: DOI2PDF detects them without
importing or installing them. If Playwright is already present, institutional routes may use it;
if browser-use is already present, an explicit `browser-assist` command may use it. Missing
packages never block OA/API/console operation. Browser-use remains unbundled because its latest
upstream release pins dependencies with unresolved security advisories; independently audit any
external installation. To add the supported Playwright path, run `DOI2PDF-browser-setup.bat` or
install `.[browser]` and then run `playwright install chromium`.

For entitlement diagnostics, point `HOLDINGS_DB` at a read-only SQLite database containing:

```sql
CREATE TABLE journals(title TEXT,publisher TEXT,issn_print TEXT,issn_e TEXT,is_free INT,coverage TEXT);
```

Use `PAPER_RADAR_DB` for the optional original `papers(doi, oa_pdf_url)` OA fallback.

## Exit codes

- `0`: valid PDF obtained / command succeeded
- `1`: command-line usage error
- `2`: invalid identifier or configuration/setup required
- `3`: automatic routes exhausted; inspect `resolver_url` for manual completion
- `4`: institutional login/configuration needs human action
- `5`: unexpected runtime failure

## License

AGPL-3.0-or-later. See `THIRD_PARTY_NOTICES.md` for upstream acknowledgements.
