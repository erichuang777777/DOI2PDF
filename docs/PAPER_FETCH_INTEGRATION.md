# paper-fetch integration matrix

This matrix is the completeness contract between upstream paper-fetch v1.0 and DOI2PDF.

| Upstream capability | DOI2PDF implementation | Status |
|---|---|---|
| Unpaywall all locations | `OpenAccessResolver.unpaywall` | Integrated |
| Semantic Scholar `openAccessPdf` | `OpenAccessResolver.semantic_scholar` | Integrated |
| DOI-to-PMC-to-Europe PMC | current NCBI ID Converter plus Europe PMC candidate | Integrated and endpoint updated |
| PMC article dataset | 2026 versioned `pmc-oa-opendata` metadata plus anonymous HTTPS PDF retrieval | Integrated; legacy FTP/package route retired |
| repository `citation_pdf_url` | shared HTTP and institutional metadata routes | Integrated |
| paper-radar SQLite fallback | `PAPER_RADAR_DB`, read-only | Integrated |
| arXiv DOI and DOI metadata search | direct arXiv mapping plus Atom API search | Integrated from Zotero PDF Hunter |
| Europe PMC REST full-text lookup | `europe_pmc_search` backend-render candidate | Integrated from Zotero PDF Hunter |
| Elsevier/Wiley/Springer TDM | `TDMResolver` | Integrated |
| all 23 publisher prefixes | `publisher_routes.ROUTES` | Integrated |
| direct PDF template routes | institutional `tpl` dispatch | Integrated |
| headless citation metadata | institutional `meta` dispatch | Integrated |
| headed BMJ/AJNR/JNM metadata | forced visible `meta` dispatch | Integrated |
| LWW signed viewer URL | institutional `lww` dispatch | Integrated |
| Ovid OCE fallback | viewer listener and signed asset fetch | Integrated |
| SFX detailed XML LWW target | `_sfx_lww_target` | Integrated |
| Ovid E3 detection/cooldown | profile-local 30-minute cooldown | Integrated |
| holdings SQLite/coverage | `Holdings`, read-only | Integrated |
| route scorecard/stats | `doi2pdf routes` and `/routes` | Integrated |
| generic form login | environment-only credentials and CSS selectors | Integrated |
| session persistence | Playwright persistent context | Equivalent replacement |
| proxy host rewrite | `EZPROXY_SUFFIX` | Integrated |
| profile lock/courtesy throttle | institution profile lock, >=15 s, <=100/day | Integrated and stricter |
| per-operation watchdog | bounded HTTP and Playwright timeouts with `finally` cleanup | Equivalent replacement |
| Patchright | standard Playwright with visible mode for routes that require it | Equivalent replacement |
| DPAPI helper | ignored local environment and protected browser profile | Equivalent secret backend |
| numeric CAPTCHA OCR | visible human completion only | Intentionally excluded by security policy |
| Zotero missing-PDF scan | `batch-zotero`, read-only source database | Integrated |
| resumable batch log | profile-local sanitized `batch_log.jsonl`, `--resume`, `--retry-failed` | Integrated |
| failed-item HTML report | `doi2pdf manual-review` | Integrated without third-party search leakage |
| linked-PDF database import | `zotero-attach`, dry-run default, backup and close-Zotero guard | Integrated |
| site-specific PDF link rules | 23 publisher routes plus Zotero translation-server translators | Equivalent replacement |
| local setup server and progress | guided web Settings, Activity, route report and Health pages | Equivalent replacement |
| title-to-DOI Crossref matching | strict identifier resolver with title similarity validation | Integrated |
| DuckDuckGo title guessing | none | Intentionally excluded: non-authoritative DOI guessing |
| Ollama link selection | optional sanitized OpenAI-compatible ranking plus deterministic fallback and PDF validation | Integrated with stricter privacy and auditability |
| remember successful publisher behavior | profile-local selector rules; provisional, verified, auto-disabled | Integrated without retaining URLs or sessions |
| Google Scholar/ResearchGate/author search links | DOI and configured library resolver only | Intentionally excluded from automatic retrieval provenance |
| Sci-Hub/Anna's Archive routes | none | Intentionally excluded: unauthorized full-text sources |

DOI2PDF additionally includes OpenAlex, Zotero translation-server metadata/attachments, a
guided local web console, live job progress, a real API credential check, and a dated
one-at-a-time acceptance corpus.

The integration is functional rather than a file-for-file copy. Duplicate downloaders,
interactive terminal setup, unrestricted browser-agent link guessing, and plaintext logs are
replaced by the shared validated pipeline, local web console, and sanitized machine-readable
records. The original source trees remain as provenance/reference material but are not imported
at runtime.

No implementation may treat a holdings miss as proof of no access, weaken the institutional
rate floor, expose credentials/signed URLs, automate CAPTCHA/SSO/MFA, or add an unauthorized
full-text source.
