# Changelog

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
