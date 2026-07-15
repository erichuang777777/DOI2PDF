# Architecture

The coding-agent surface is a concise skill paired with the installed `doi2pdf` CLI. The
release skill archive embeds the matching wheel, while the HTML application remains the
human-only setup and authentication surface. Secret values flow from HTML POST to the ignored
local `.env` and process environment; only boolean configured state is rendered afterward.

Web fetches are background jobs held in a lock-protected, bounded in-memory registry. Pipeline
callbacks emit percentage, stage, source, and status only—never URLs or exception details.
The progress and activity pages poll read-only JSON snapshots; final PDF access still uses
random server-side file tokens. Monitoring failure is isolated from retrieval execution.

`DOI2PDF.fetch()` is the sole retrieval orchestrator. It normalizes or resolves the input,
then walks four ordered layers and stops only when a response passes PDF magic-byte
validation.

1. Open access: Unpaywall locations, Semantic Scholar, OpenAlex OA locations, Europe PMC,
   and repository landing-page metadata.
2. Publisher TDM: Elsevier, Wiley, and Springer Nature official endpoints using the user's
   own optional API credentials.
3. Institutional: Zotero translator attachment discovery followed by a serialized,
   persistent OpenAthens/EZproxy Playwright session.
4. Resolver: an SFX/OpenURL link for manual completion.

All output is written to a temporary file and atomically renamed. Results contain route,
layer, attempt statuses, byte count, SHA-256, and the manual resolver when applicable.

The browser profile has a cross-process lock, a hard minimum 15-second courtesy interval,
and a maximum of 100 institutional attempts per local day. Its access log contains only
timestamps, request kind, and DOI—not credentials or cookies.

Institutional dispatch uses the complete paper-fetch prefix registry. `tpl` routes construct
authorized publisher PDF URLs; `meta` routes resolve the article and follow
`citation_pdf_url`; selected metadata routes force visible navigation; `lww` routes walk the
viewer-to-signed-PDF chain and fall back to Ovid OCE with a 30-minute E3 licence-seat
cooldown. All paths retain magic-byte validation and emit sanitized status classifications.

The optional holdings subsystem retrieves ISSN, journal, and year from Crossref, then reads
the user's SQLite journal table in read-only mode. Its result accompanies the institutional
attempt but an unknown or out-of-coverage result does not silently block retrieval. The
route-health subsystem aggregates only local status fields and never exposes signed URLs,
headers, cookies, or credentials.

After registered publisher, citation metadata, and Zotero translator routes, the institutional
browser may reuse a learned selector or optionally ask an OpenAI-compatible model to rank up to
20 sanitized candidates. Only hostname, visible text, ARIA label, and URL path leave the browser;
query strings and full page content do not. The download still runs through the authorized
Playwright context and must pass magic-byte validation. Successful selectors are stored in the
private browser profile, promoted after two successes, and disabled after three consecutive
failures. The store never retains candidate URLs, signed parameters, cookies, or credentials.

The local web interface is a loopback-only wrapper around the same package. It has no
separate retrieval logic, so CLI, web, Zotero batch, and agent-skill behavior share the same
validation and safety invariants.

Acceptance testing uses a small source-controlled corpus of real DOI records with a dated
no-access baseline. The CLI lists cases and the web console submits exactly one case through
the ordinary background retrieval path. API credential diagnostics likewise use real
provider requests, but return only stable classifications and HTTP status codes. Neither
feature stores or renders secrets, and neither provides a bulk execution path.

On first launch, the web application requires a real API contact email and records setup
completion in the ignored `.env`. Retrieved files are exposed to the browser only through
random in-memory tokens; clients cannot request arbitrary filesystem paths. Tokens expire
when the local server stops.

The Library Access Assistant performs syntax-only detection on a user-pasted HTTPS link. It
recognizes OpenAthens redirectors, EZproxy starting-point URLs, and common proxy-by-hostname
suffixes, discards the article target, and asks for confirmation before saving one inferred
setting. It never fetches the pasted target or attempts institution discovery from an email.
Web-initiated login runs in a background thread with visible Chromium for up to three minutes,
so SSO/MFA remains human-controlled without blocking on terminal input.
