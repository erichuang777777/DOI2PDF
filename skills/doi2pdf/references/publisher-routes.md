# Publisher and entitlement routes

Use `doi2pdf routes --json` as the runtime source of truth. The institutional registry
contains four route shapes inherited from paper-fetch v1.0:

- `tpl`: Wiley, Springer/BMC, NEJM, Sage, Taylor & Francis, AJR, RSNA, and World Scientific.
- `meta`: JAMA, OUP, Pediatrics, ERJ, Journal of Neurosurgery, and Nature.
- headed `meta`: BMJ, AJNR, and Journal of Nuclear Medicine.
- `lww`: LWW/AHA/A&A/CJASN prefixes through signed viewer URLs and Ovid OCE fallback.

Set an organization-issued `EZPROXY_SUFFIX` for rewritten publisher hosts. An OpenAthens
Redirector can authorize public targets instead. Never reuse an endpoint from another
institution. Keep headed routes visible; a headless WAF failure is not proof that the route
or article is unavailable.

Use `doi2pdf holdings <DOI> --json` before diagnosing a publisher route. `subscribed=true`
and `covered=true` plus a persistent failure is actionable. `covered=false` means the
article year may be outside the subscription. `subscribed=null` means unknown and must not
be treated as no access. Configure `HOLDINGS_DB` with a read-only SQLite database:

```sql
CREATE TABLE journals(
  title TEXT, publisher TEXT, issn_print TEXT, issn_e TEXT,
  is_free INT, coverage TEXT
);
```

Use `doi2pdf routes --json` after real attempts to inspect sanitized statuses. Stop on
`cf_block`, `cf_challenge`, or `rate_limited`. Treat `license_seat_e3` as an occupied Ovid
seat; close the user's Ovid tabs and respect the local cooldown. Treat `auth_required`,
profile busy, and timeout as retryable session conditions, not missing full text.

Plain EZproxy/NetScaler forms may use `LIBRARY_LOGIN_URL`, `LIBRARY_USERNAME`,
`LIBRARY_PASSWORD`, and CSS selectors from the ignored local environment. Never place these
values in prompts or command arguments. OpenAthens/Shibboleth, CAPTCHA, and MFA remain a
visible human login step; do not automate or solve them.
