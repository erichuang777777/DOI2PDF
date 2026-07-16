# Security

Report security issues privately through GitHub Security Advisories for this repository.
Do not include passwords, API keys, cookies, browser profiles, institutional URLs containing
personal tokens, or complete access logs in an issue.

DOI2PDF binds its local web interface to `127.0.0.1`. Do not expose it to a network or public
reverse proxy. Treat the Playwright profile and `.env` as private account material.

The project supports only lawful access using public OA content, official publisher APIs,
and the user's own institutional entitlement. Reports requesting paywall bypasses, CAPTCHA
solving, shared credentials, or pirate-source integration are out of scope.

Optional LLM ranking sends only sanitized candidate text, ARIA labels, publisher hostname,
and URL paths without query strings. Use a provider whose data policy you accept, or a local
loopback model. Never modify the ranker to send page HTML, cookies, headers, signed URLs,
institutional identifiers, or credentials. LLM output is advisory and cannot bypass PDF
validation, institutional rate limits, or interactive SSO/MFA.

The browser-use helper is not bundled in the secure installer while its latest upstream release
pins dependencies with known advisories. DOI2PDF uses visible Playwright for authorized login and
manual verification until an audited-compatible browser-use release is available. The helper also
requires the explicit `DOI2PDF_BROWSER_USE_ENABLED=true` opt-in even if installed externally.
