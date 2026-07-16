# Changelog

## 0.8.5 - 2026-07-16

- Replaced the browser-use environment-variable gate with runtime detection of optional
  Playwright and browser-use installations.
- Made `doctor` and `/health` expose both optional browser capabilities without importing or
  installing them.
- Allowed an explicitly invoked `browser-assist` command to use an existing browser-use install;
  otherwise it returns stable `unavailable` JSON while OA/API/console operation remains normal.

## 0.8.4 - 2026-07-16

- Made the Windows one-click setup lightweight by default: OA, APIs, Zotero, resolver, CLI,
  and the web console no longer download Playwright or Chromium during first launch.
- Added `DOI2PDF-browser-setup.bat` for explicit on-demand installation when authorized
  OpenAthens, EZproxy, or visible publisher verification is needed.
- Kept the agent skill installer lightweight by default and retained `--with-browser` as its
  matching explicit opt-in.

## 0.8.3 - 2026-07-16

- Made browser-use assistance explicitly disabled by default, including when browser-use was
  installed separately in the environment.
- Added the `DOI2PDF_BROWSER_USE_ENABLED` opt-in gate and stable `disabled` CLI status for agents.
- Kept visible Playwright as the supported default for institutional login and manual verification.

## 0.8.2 - 2026-07-16

- Integrated the first weekly Dependabot maintenance batch in one tested release rather than
  shipping nine independent dependency changes.
- Updated GitHub Actions checkout to v7, setup-python to v6, and upload-artifact to v7, removing
  the Node 20 deprecation warning from the release pipeline.
- Raised the tested minimums for Playwright 1.61.0, setuptools 83.0.0, Twine 6.2.0,
  Ruff 0.15.21, and pip-audit 2.10.1.
- Updated Requests to 2.34.2 and pypdf to 6.13.3 or newer.
- Temporarily removed browser-use from the bundled installer because its latest upstream release
  pins multiple dependencies with known advisories. Visible Playwright remains the supported
  institutional login and manual-verification path.

## 0.8.1 - 2026-07-16

- Made `doctor --json` distinguish a valid configuration from completed first-run setup,
  and exposed always-available OpenAlex, PMC, and arXiv routes accurately.
- Stream PDF and metadata responses with hard 100 MiB and 10 MiB bounds instead of loading
  untrusted responses without a limit.
- Validate the PDF header, final EOF marker, readable page tree, and nonzero page count before
  writing or learning a publisher rule.
- Applied equivalent declared-size and post-read checks to Playwright response capture.
- Bounded the tested browser-use dependency to the compatible 0.13 series and added automated
  dependency auditing plus weekly Dependabot checks for Python and GitHub Actions.

## 0.8.0 - 2026-07-16

- Enforced explicit campus/off-campus retrieval policy. Auto mode enters campus mode only
  when a local address matches a user-configured CIDR.
- Added current PMC AWS article-dataset discovery and retired the obsolete PMC FTP/package
  route. Reusable PMC PDFs are checked through official version metadata.
- Fixed batch runs that could omit failed phase-one items when institutional fallback was
  disabled.
- Added browser-use as an optional, visible manual-verification assistant with CAPTCHA solving
  disabled; Playwright remains the deterministic authorized download context.
- Added bounded institutional rate limits, sanitized machine results and Web activity logs,
  safer `.env` round-tripping, XML hardening, and release-version User-Agent strings.
- Added skill/package contract tests, cross-platform CI linting, tag/version checks, package
  validation, and a clean wheel-based skill installer path.
- Preserved Zotero's `{ZoteroKey}_{FirstAuthorLastName}_{Year}.pdf` naming behavior.

### Known access constraints

- Publisher and institutional routes require the user's own entitlement and must be validated
  by that user on their licensed network or OpenAthens/EZproxy session.
- CAPTCHA, Cloudflare verification, SSO, and MFA remain interactive; DOI2PDF does not solve or
  bypass them.
- A PMC record may expose reusable manuscript text without an article PDF. DOI2PDF reports that
  distinction instead of treating PMC presence as proof that a PDF is available.
