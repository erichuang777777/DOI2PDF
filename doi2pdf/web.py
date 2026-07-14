from __future__ import annotations

import html
import json
import os
import threading
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import __version__
from .config import Settings
from .naming import build_pdf_path
from .pipeline import DOI2PDF


app = FastAPI(title="DOI2PDF", version=__version__)
ENV_PATH = Path(os.getenv("DOI2PDF_ENV_FILE", ".env"))


def _layout(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · DOI2PDF</title>
<style>
:root{{--ink:#17212b;--muted:#637083;--blue:#1769aa;--pale:#eef6fc;--line:#d9e3ec;--ok:#137333;--bad:#b3261e}}
*{{box-sizing:border-box}} body{{margin:0;background:#f6f8fa;color:var(--ink);font:16px/1.5 system-ui,"Segoe UI",sans-serif}}
main{{max-width:900px;margin:36px auto;padding:0 20px}} .card{{background:white;border:1px solid var(--line);border-radius:14px;padding:24px;margin:18px 0;box-shadow:0 4px 20px #15324b0d}}
h1{{font-size:2rem;margin:.2rem 0}} h2{{font-size:1.2rem;margin-top:0}} .muted{{color:var(--muted)}}
label{{display:block;font-weight:650;margin-top:14px}} input{{width:100%;padding:11px;border:1px solid #aebdca;border-radius:8px;font:inherit}}
.check{{display:flex;gap:9px;align-items:center;font-weight:500}} .check input{{width:auto}}
button,.button{{display:inline-block;background:var(--blue);color:white;border:0;border-radius:9px;padding:11px 18px;font-weight:700;text-decoration:none;cursor:pointer;margin-top:18px}}
.secondary{{background:#596b7b}} table{{width:100%;border-collapse:collapse;font-size:.9rem}} th,td{{text-align:left;border-bottom:1px solid var(--line);padding:8px;vertical-align:top;word-break:break-word}}
.ok{{color:var(--ok);font-weight:700}} .bad{{color:var(--bad);font-weight:700}} code{{background:var(--pale);padding:2px 5px;border-radius:4px}} nav a{{margin-right:14px}}
</style></head><body><main><nav><a href="/">Fetch</a><a href="/configure">Settings</a><a href="/health">Health</a></nav>{body}</main></body></html>"""


def _settings() -> Settings:
    # The settings page can update .env without restarting the local server.
    try:
        from dotenv import load_dotenv

        load_dotenv(ENV_PATH, override=True)
    except ImportError:
        pass
    return Settings.from_env()


def _masked(value: str) -> str:
    return "configured" if value else "not configured"


def _write_env(updates: dict[str, str]) -> None:
    existing: dict[str, str] = {}
    order: list[str] = []
    if ENV_PATH.exists():
        for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if raw and not raw.lstrip().startswith("#") and "=" in raw:
                key, value = raw.split("=", 1)
                existing[key.strip()] = value
                order.append(key.strip())
    for key, value in updates.items():
        # Blank password-style fields mean "keep existing", not erase accidentally.
        if value or key not in existing:
            existing[key] = value.replace("\r", "").replace("\n", "")
        if key not in order:
            order.append(key)
    ENV_PATH.write_text("\n".join(f"{key}={existing[key]}" for key in order) + "\n", encoding="utf-8")


def _parse_body(body: bytes) -> dict[str, str]:
    parsed = urllib.parse.parse_qs(body.decode("utf-8"), keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items()}


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    settings = _settings()
    issues = settings.validate()
    warning = "" if not issues else '<p class="bad">' + html.escape(" ".join(issues)) + "</p>"
    return _layout("Fetch", f"""
<h1>DOI2PDF</h1><p class="muted">One-click lawful paper retrieval for clinical and research work.</p>
{warning}<section class="card"><h2>Retrieve a paper</h2>
<form method="post" action="/fetch">
<label for="identifier">DOI, PMID, DOI URL, or exact title</label><input id="identifier" name="identifier" required autofocus placeholder="10.1186/s12984-023-01168-x">
<label for="output_dir">Download folder</label><input id="output_dir" name="output_dir" value="downloads">
<label for="zotero_key">Zotero key (optional)</label><input id="zotero_key" name="zotero_key" maxlength="8" placeholder="9ET75JMH">
<label class="check"><input type="checkbox" name="use_institution" value="1" checked> Use my configured OpenAthens/EZproxy session after OA and TDM routes</label>
<button type="submit">Retrieve PDF</button></form></section>
<section class="card"><h2>Safety</h2><p>This tool uses public OA sources, official publisher APIs, and your own authorized library session. It does not bypass paywalls or share credentials. Institutional retrieval is serialized, delayed, and daily-limited.</p></section>""")


@app.post("/fetch", response_class=HTMLResponse)
async def fetch(request: Request) -> str:
    form = _parse_body(await request.body())
    identifier = form.get("identifier", "").strip()
    output_dir = Path(form.get("output_dir", "downloads") or "downloads")
    use_institution = form.get("use_institution") == "1"
    if not identifier:
        return _layout("Error", '<section class="card"><p class="bad">An identifier is required.</p></section>')

    client = DOI2PDF(_settings())
    try:
        doi = await run_in_threadpool(client.identifiers.resolve, identifier)
        provisional = output_dir / f".{doi.replace('/', '_')}.download.pdf"
        result = await run_in_threadpool(client.fetch, doi, provisional, use_institution)
        if result.ok:
            final_path = build_pdf_path(
                output_dir,
                zotero_key=form.get("zotero_key") or None,
                doi=doi,
                metadata=result.metadata.get("zotero") or {},
            )
            provisional.replace(final_path)
            result.path = final_path
    except Exception as exc:
        return _layout("Error", f'<section class="card"><h2>Retrieval error</h2><p class="bad">{html.escape(type(exc).__name__ + ": " + str(exc))}</p><a class="button" href="/">Try again</a></section>')

    rows = "".join(
        f"<tr><td>{html.escape(attempt.layer)}</td><td>{html.escape(attempt.source)}</td>"
        f"<td>{html.escape(attempt.status)}</td><td>{html.escape(attempt.detail or '')}</td></tr>"
        for attempt in result.attempts
    )
    if result.ok:
        summary = f'<p class="ok">PDF retrieved successfully.</p><p><strong>File:</strong> <code>{html.escape(str(result.path.resolve()))}</code></p><p><strong>Route:</strong> {html.escape(str(result.layer))} / {html.escape(str(result.route))} · {result.bytes:,} bytes</p>'
    else:
        resolver = f'<p><a class="button secondary" target="_blank" href="{html.escape(result.resolver_url, quote=True)}">Open library resolver</a></p>' if result.resolver_url else ""
        summary = '<p class="bad">No automatic route produced a verified PDF.</p>' + resolver
    return _layout("Result", f'<h1>Result</h1><section class="card">{summary}<p><strong>DOI:</strong> {html.escape(result.doi)}</p></section><section class="card"><h2>Route report</h2><table><thead><tr><th>Layer</th><th>Source</th><th>Status</th><th>Detail</th></tr></thead><tbody>{rows}</tbody></table></section><a class="button" href="/">Retrieve another</a>')


@app.get("/configure", response_class=HTMLResponse)
def configure() -> str:
    settings = _settings()
    return _layout("Settings", f"""
<h1>Settings</h1><p class="muted">Stored only in the ignored local <code>.env</code> file. Never enter an OpenAthens password here.</p>
<section class="card"><form method="post" action="/configure">
<label>Contact email</label><input type="email" name="DOI2PDF_CONTACT_EMAIL" value="{html.escape(settings.contact_email, quote=True)}" required>
<label>Unpaywall email</label><input type="email" name="UNPAYWALL_EMAIL" value="{html.escape(settings.unpaywall_email, quote=True)}">
<label>PubMed API key <span class="muted">({_masked(settings.pubmed_api_key)})</span></label><input type="password" name="PUBMED_API_KEY" autocomplete="off">
<label>Semantic Scholar API key <span class="muted">({_masked(settings.semantic_scholar_api_key)})</span></label><input type="password" name="S2_API_KEY" autocomplete="off">
<label>Elsevier TDM key <span class="muted">({_masked(settings.elsevier_api_key)})</span></label><input type="password" name="ELSEVIER_TDM_KEY" autocomplete="off">
<label>Wiley TDM token <span class="muted">({_masked(settings.wiley_tdm_token)})</span></label><input type="password" name="WILEY_TDM_TOKEN" autocomplete="off">
<label>Springer API key <span class="muted">({_masked(settings.springer_api_key)})</span></label><input type="password" name="SPRINGER_API_KEY" autocomplete="off">
<label>OpenAthens redirector prefix</label><input name="OPENATHENS_REDIRECTOR_PREFIX" value="{html.escape(settings.openathens_redirector_prefix, quote=True)}" placeholder="https://go.openathens.net/redirector/YOUR-DOMAIN?url=">
<label>EZproxy prefix/template</label><input name="EZPROXY_PREFIX" value="{html.escape(settings.ezproxy_prefix, quote=True)}">
<label>Library resolver template</label><input name="LIBRARY_RESOLVER_TEMPLATE" value="{html.escape(settings.resolver_template, quote=True)}" placeholder="https://resolver.example/openurl?doi={{doi}}">
<button type="submit">Save settings</button></form></section>
<section class="card"><h2>Institutional session</h2><p>After saving your own OpenAthens or EZproxy prefix, open the persistent Chromium login. Complete SSO/MFA in Chromium, then return to the DOI2PDF launcher window and press Enter.</p><form method="post" action="/institution-login"><button class="secondary" type="submit">Open institutional login</button></form></section>""")


@app.post("/configure")
async def save_configuration(request: Request):
    allowed = {
        "DOI2PDF_CONTACT_EMAIL", "UNPAYWALL_EMAIL", "PUBMED_API_KEY", "S2_API_KEY",
        "ELSEVIER_TDM_KEY", "WILEY_TDM_TOKEN", "SPRINGER_API_KEY",
        "OPENATHENS_REDIRECTOR_PREFIX", "EZPROXY_PREFIX", "LIBRARY_RESOLVER_TEMPLATE",
    }
    form = _parse_body(await request.body())
    _write_env({key: value.strip() for key, value in form.items() if key in allowed})
    return RedirectResponse("/configure?saved=1", status_code=303)


@app.post("/institution-login", response_class=HTMLResponse)
async def institution_login() -> str:
    client = DOI2PDF(_settings())
    try:
        await run_in_threadpool(client.institution.login)
    except Exception as exc:
        return _layout("Login error", f'<section class="card"><p class="bad">{html.escape(type(exc).__name__ + ": " + str(exc))}</p><a class="button" href="/configure">Back to settings</a></section>')
    return _layout("Login ready", '<section class="card"><p class="ok">The persistent institutional browser session is ready.</p><a class="button" href="/">Retrieve a paper</a></section>')


@app.get("/health")
def health() -> JSONResponse:
    settings = _settings()
    return JSONResponse({
        "ok": not settings.validate(), "version": __version__, "issues": settings.validate(),
        "routes": {
            "unpaywall": bool(settings.unpaywall_email),
            "zotero_translation_server": settings.translator_enabled,
            "openathens": bool(settings.openathens_redirector_prefix),
            "ezproxy": bool(settings.ezproxy_prefix),
            "resolver": bool(settings.resolver_template),
        },
    })


def main() -> None:
    import uvicorn

    url = "http://127.0.0.1:8765"
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")


if __name__ == "__main__":
    main()
