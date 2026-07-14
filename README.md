# DOI2PDF

DOI2PDF combines Zotero PDF Hunter, the lawful route ladder from paper-fetch, and Zotero
translation-server metadata into one provenance-aware tool.

It tries, in order:

1. **Open access** — every Unpaywall OA location, Semantic Scholar `openAccessPdf`, every
   OpenAlex location, PMC→Europe PMC rendering, and repository `citation_pdf_url`.
2. **Publisher TDM APIs** — Elsevier, Wiley, and Springer using credentials registered by
   the user with those publishers.
3. **Institutional access** — PDF attachments exposed by Zotero translators, then the
   user's own OpenAthens Redirector or EZproxy URL in a persistent Playwright session.
   The default is a visible browser so SSO/MFA can be completed normally; the session is
   reused afterward.
4. **Library resolver** — prints the configured SFX/OpenURL link for manual completion.

Every downloaded response is checked for a real `%PDF-` header and written atomically.
The JSON result records every route and its provenance.

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
access. Agents call the global `doi2pdf` command and parse one JSON envelope from stdout.
If setup is required, they launch `doi2pdf-web`; API keys are entered only in the local HTML
page, stored in the ignored `.env`, and never rendered back to the browser or agent.

## Local web console

The local-only console provides four operational views:

- **Fetch** starts a background retrieval without blocking the browser request.
- **Progress** shows the current lawful layer, completion percentage, and sanitized route events.
- **Activity** monitors the latest 50 jobs and updates once per second.
- **Settings** manages environment configuration without rendering stored API-key values.

Activity logs stay in memory and reset when the server restarts. They omit candidate URLs,
request headers, cookies, local output paths, and API keys. At most two web retrieval jobs run
concurrently; institutional requests retain their separate persistent rate limits.

## One-click Windows app

Double-click **`DOI2PDF.bat`**. On the first run it creates an isolated environment,
installs DOI2PDF and Chromium, copies the local settings template, starts the server on
`127.0.0.1`, and opens a guided browser setup. Enter a real contact email, choose the PDF
folder, and optionally add your own library access links or publisher API keys. Later starts
reuse the installation and go directly to retrieval.

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
playwright install chromium
Copy-Item .env.example .env
```

Fill in your email, and only the API keys/library endpoints you actually use. Do not put
OpenAthens passwords in `.env`; login happens in the browser and cookies remain in the
local Playwright profile.

## Usage

```powershell
# Validate configuration (machine-readable flag works before or after the command)
doi2pdf doctor --json

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
```

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

## Exit codes

- `0`: valid PDF obtained / command succeeded
- `1`: command-line usage error
- `2`: invalid identifier or configuration/setup required
- `3`: automatic routes exhausted; inspect `resolver_url` for manual completion
- `4`: institutional login/configuration needs human action
- `5`: unexpected runtime failure

## License

AGPL-3.0-or-later. See `THIRD_PARTY_NOTICES.md` for upstream acknowledgements.
