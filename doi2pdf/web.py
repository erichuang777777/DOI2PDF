from __future__ import annotations

import html
import json
import os
import re
import threading
import time
import urllib.parse
import uuid
import webbrowser
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from . import __version__
from .acceptance import corpus
from .api_probe import probe_all
from .config import Settings
from .capabilities import browser_capabilities
from .naming import build_pdf_path
from .learned_rules import RuleStore
from .library_detect import detect_library_link
from .pipeline import DOI2PDF
from .publisher_routes import ROUTES
from .route_health import summary as route_health_summary


app = FastAPI(title="DOI2PDF", version=__version__)
ENV_PATH = Path(os.getenv("DOI2PDF_ENV_FILE", ".env"))
SECRET_ENV_KEYS = {
    "PUBMED_API_KEY", "S2_API_KEY", "ELSEVIER_TDM_KEY", "ELSEVIER_INSTTOKEN",
    "WILEY_TDM_TOKEN", "SPRINGER_API_KEY", "LIBRARY_USERNAME", "LIBRARY_PASSWORD",
    "DOI2PDF_LLM_API_KEY",
}
_FILES: dict[str, Path] = {}
_JOBS: dict[str, dict[str, Any]] = {}
_JOB_LOCK = threading.RLock()
MAX_ACTIVE_WEB_JOBS = 2
_LOGIN_STATE: dict[str, Any] = {"state": "idle", "message": "No login session is running."}

# The console is served only on loopback, but loopback binding alone does not
# stop a cross-site POST or DNS rebinding: any page the user has open in a
# browser can POST to http://127.0.0.1:8765 and rewrite .env, start a login, or
# launch a fetch. We require a loopback Host header (defeats DNS rebinding) and,
# for state-changing methods, a same-origin Origin/Referer (defeats CSRF).
BIND_HOST = "127.0.0.1"
BIND_PORT = 8765
_ALLOWED_HOSTS = frozenset({
    f"{BIND_HOST}:{BIND_PORT}", f"localhost:{BIND_PORT}", BIND_HOST, "localhost",
})
_ALLOWED_ORIGINS = frozenset({
    f"http://{BIND_HOST}:{BIND_PORT}", f"http://localhost:{BIND_PORT}",
})
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _origin_guard(method: str, headers: Any) -> str | None:
    """Return a rejection reason if the request is not a trusted local one.

    Returns ``None`` when the request may proceed. Kept as a pure function so it
    can be unit-tested without an ASGI stack.
    """
    host = (headers.get("host") or "").split(",")[0].strip().lower()
    if host not in _ALLOWED_HOSTS:
        return "host_not_allowed"
    if method.upper() in _SAFE_METHODS:
        return None
    origin = (headers.get("origin") or "").strip().lower().rstrip("/")
    if origin:
        return None if origin in _ALLOWED_ORIGINS else "cross_origin"
    referer = (headers.get("referer") or "").strip()
    if referer:
        parts = urllib.parse.urlsplit(referer)
        base = f"{parts.scheme}://{parts.netloc}".lower()
        return None if base in _ALLOWED_ORIGINS else "cross_origin"
    # A same-origin browser form POST always carries Origin (and usually
    # Referer). Reject state-changing requests that carry neither.
    return "missing_origin"


@app.middleware("http")
async def enforce_local_origin(request: Request, call_next):
    if _origin_guard(request.method, request.headers):
        return JSONResponse(
            {"detail": "Request blocked by DOI2PDF local-origin protection."},
            status_code=403,
        )
    return await call_next(request)


API_HELP = {
    "pubmed": ("Optional. Create it under API Key Management in My NCBI account settings.", "https://account.ncbi.nlm.nih.gov/settings/"),
    "semantic": ("Optional; public requests work without a key but may be throttled.", "https://www.semanticscholar.org/product/api"),
    "elsevier": ("Register your own key; full-text entitlement still depends on your licence.", "https://dev.elsevier.com/"),
    "wiley": ("Accept Wiley's TDM terms to receive a personal access token.", "https://onlinelibrary.wiley.com/library-info/resources/text-and-datamining"),
    "springer": ("Register in Springer Nature API Management.", "https://dev.springernature.com/docs/quick-start/api-access/"),
    "unpaywall": ("No key is required; Unpaywall asks for a real contact email.", "https://unpaywall.org/products/api"),
}
NETWORK_MODE_HELP = {
    "auto": "Detect configured campus IP ranges; otherwise use OA/API and OpenAthens only.",
    "off_campus": "Use OA, OpenAthens, and official APIs only; skip direct-campus and EZproxy routes.",
    "campus": "Use OA/API first, then direct campus access, EZproxy, and browser-assisted discovery.",
}


def _network_mode_field(settings: Settings) -> str:
    current = settings.normalized_network_mode()
    options = "".join(
        f'<option value="{value}" {"selected" if value == current else ""}>{html.escape(label)}</option>'
        for value, label in (
            ("auto", "Auto — match configured campus IP ranges"),
            ("off_campus", "Off-campus — OA / OpenAthens / API only"),
            ("campus", "Campus — allow institutional fallback and browser assist"),
        )
    )
    return (
        '<label>Network mode</label>'
        f'<select name="DOI2PDF_NETWORK_MODE">{options}</select>'
        f'<p class="muted">{html.escape(NETWORK_MODE_HELP[current])}</p>'
    )


@app.middleware("http")
async def prevent_settings_cache(request: Request, call_next):
    response = await call_next(request)
    if request.url.path in {"/setup", "/configure"} or request.url.path.startswith(("/api/jobs", "/jobs/")):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response


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
.secondary{{background:#596b7b}} .success{{background:var(--ok)}} table{{width:100%;border-collapse:collapse;font-size:.9rem}} th,td{{text-align:left;border-bottom:1px solid var(--line);padding:8px;vertical-align:top;word-break:break-word}}
.ok{{color:var(--ok);font-weight:700}} .bad{{color:var(--bad);font-weight:700}} code{{background:var(--pale);padding:2px 5px;border-radius:4px}} nav a{{margin-right:14px}}
.steps{{display:flex;gap:8px;margin:20px 0}} .step{{flex:1;padding:9px;text-align:center;border-radius:8px;background:#e8edf2;color:var(--muted);font-size:.9rem}} .step.active{{background:var(--blue);color:white;font-weight:700}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}} .status{{border:1px solid var(--line);border-radius:9px;padding:12px}} .status strong{{display:block}}
details{{margin-top:16px}} select{{width:100%;padding:11px;border:1px solid #aebdca;border-radius:8px;font:inherit;background:white}}
#working{{display:none;position:fixed;inset:0;background:#f6f8faf2;z-index:9;align-items:center;justify-content:center;text-align:center;padding:20px}} #working.show{{display:flex}} .spinner{{width:48px;height:48px;border:5px solid #dbe7f0;border-top-color:var(--blue);border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 18px}} @keyframes spin{{to{{transform:rotate(360deg)}}}}
.progress-track{{height:16px;background:#e1e8ee;border-radius:999px;overflow:hidden}} .progress-bar{{height:100%;width:0;background:var(--blue);transition:width .35s ease}}
.log{{list-style:none;padding:0;margin:0;max-height:360px;overflow:auto}} .log li{{padding:9px 0;border-bottom:1px solid var(--line);font-family:ui-monospace,Consolas,monospace;font-size:.86rem}} .pill{{display:inline-block;padding:2px 8px;border-radius:999px;background:var(--pale);font-size:.78rem}}
</style></head><body><main><nav><a href="/">Fetch</a><a href="/acceptance">Acceptance</a><a href="/routes">Routes</a><a href="/rules">Learned rules</a><a href="/activity">Activity</a><a href="/configure">Settings</a><a href="/health">Health</a></nav>{body}</main></body></html>"""


def _settings() -> Settings:
    # The settings page can update .env without restarting the local server.
    try:
        from dotenv import load_dotenv

        load_dotenv(ENV_PATH, override=True)
    except ImportError:
        pass
    return Settings.from_env()


def _secret_field(label: str, key: str, configured: bool) -> str:
    """Render secret state, never the secret value."""
    state = "configured — leave blank to keep" if configured else "not configured"
    return (
        f'<label>{html.escape(label)} <span class="muted">({state})</span></label>'
        f'<input type="password" name="{html.escape(key, quote=True)}" value="" '
        'autocomplete="new-password" spellcheck="false" placeholder="Enter a new key">'
    )


def _application_help(provider: str, label: str = "Official application instructions") -> str:
    description, url = API_HELP[provider]
    return f'<p class="muted">{html.escape(description)} <a target="_blank" rel="noopener noreferrer" href="{html.escape(url, quote=True)}">{html.escape(label)}</a></p>'


def _write_env(updates: dict[str, str]) -> None:
    from dotenv import dotenv_values, set_key

    existing = {key: value or "" for key, value in dotenv_values(ENV_PATH).items()} if ENV_PATH.exists() else {}
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENV_PATH.touch(exist_ok=True)
    for key, value in updates.items():
        # Blank secret fields mean "keep existing"; ordinary fields can be cleared.
        if not value and key in SECRET_ENV_KEYS and key in existing:
            continue
        clean = value.replace("\r", "").replace("\n", "")
        # python-dotenv performs the escaping, so spaces, #, quotes, and Windows
        # paths round-trip instead of being silently truncated on the next run.
        set_key(str(ENV_PATH), key, clean, quote_mode="always")
        existing[key] = clean
    try:
        ENV_PATH.chmod(0o600)
    except OSError as exc:
        # On POSIX a failure here means the secrets file is left world-readable;
        # warn rather than fail silently. (chmod is a no-op on Windows.)
        if os.name == "posix":
            import warnings

            warnings.warn(f"Could not restrict {ENV_PATH} permissions to 0600: {exc}", stacklevel=2)
    # Make saved values available to the running CLI/web process immediately.
    for key, value in existing.items():
        os.environ[key] = value


def _parse_body(body: bytes) -> dict[str, str]:
    parsed = urllib.parse.parse_qs(body.decode("utf-8"), keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items()}


def _resolve_output_dir(raw: str, settings: Settings) -> Path:
    """Confine a browser-supplied save folder to the configured download root.

    Without this, a form value like ``../../`` or an absolute path could plant a
    valid-PDF blob anywhere the process can write (e.g. a Startup folder). The
    CLI's ``-o`` is deliberately unrestricted local-user autonomy; only the web
    form is confined.
    """
    root = Path(settings.download_dir).expanduser().resolve()
    requested = Path((raw or "").strip() or settings.download_dir).expanduser().resolve()
    if requested == root or requested.is_relative_to(root):
        return requested
    raise ValueError("Save folder must be inside the configured download folder.")


def _register_file(path: Path) -> str:
    resolved = path.resolve(strict=True)
    token = uuid.uuid4().hex
    _FILES[token] = resolved
    if len(_FILES) > 100:
        _FILES.pop(next(iter(_FILES)))
    return token


def _redact(value: str) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ")[:500]
    for key in SECRET_ENV_KEYS:
        secret = os.getenv(key, "")
        if secret:
            text = text.replace(secret, "[redacted]")
    return re.sub(r"https?://\S+", "[redacted-url]", text, flags=re.I)


def _job_event(job_id: str, event: dict[str, Any], *, state: str | None = None) -> None:
    clean = {
        "time": time.strftime("%H:%M:%S", time.localtime()),
        "percent": max(0, min(100, int(event.get("percent", 0)))),
        "stage": _redact(event.get("stage", "working")),
        "message": _redact(event.get("message", "Working")),
    }
    for key in ("source", "status"):
        if event.get(key):
            clean[key] = _redact(event[key])
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job.update({"percent": clean["percent"], "stage": clean["stage"], "message": clean["message"], "updated_at": time.time()})
        if state:
            job["state"] = state
        job["events"].append(clean)
        del job["events"][:-100]


def _new_job(identifier: str) -> str:
    with _JOB_LOCK:
        active = sum(job["state"] in {"queued", "running"} for job in _JOBS.values())
        if active >= MAX_ACTIVE_WEB_JOBS:
            raise RuntimeError("Two retrievals are already running. Wait for one to finish.")
        job_id = uuid.uuid4().hex
        now = time.time()
        _JOBS[job_id] = {
            "id": job_id, "identifier": _redact(identifier), "state": "queued", "percent": 0,
            "stage": "queued", "message": "Waiting to start", "created_at": now, "updated_at": now,
            "events": [], "result": None, "file_token": None, "error": None,
        }
        if len(_JOBS) > 50:
            oldest_finished = next((key for key, value in _JOBS.items() if value["state"] not in {"queued", "running"}), None)
            if oldest_finished and oldest_finished != job_id:
                _JOBS.pop(oldest_finished, None)
    _job_event(job_id, {"percent": 0, "stage": "queued", "message": "Retrieval queued"})
    return job_id


def _job_snapshot(job: dict[str, Any]) -> dict[str, Any]:
    result = job.get("result")
    payload = {key: job[key] for key in ("id", "identifier", "state", "percent", "stage", "message", "created_at", "updated_at", "events", "error")}
    payload["result_url"] = f'/jobs/{job["id"]}/result' if result is not None else None
    if result is not None:
        payload["result"] = {
            "ok": result.ok, "doi": result.doi, "layer": result.layer, "route": result.route,
            "bytes": result.bytes, "filename": result.path.name if result.path else None,
            "resolver_url": result.resolver_url,
        }
    return payload


def _route_status(settings: Settings) -> str:
    entries = (
        ("Open access", bool(settings.unpaywall_email), "Unpaywall, OpenAlex, PMC Cloud, Europe PMC"),
        ("Publisher APIs", bool(settings.elsevier_api_key or settings.wiley_tdm_token or settings.springer_api_key), "Optional Elsevier, Wiley, Springer keys"),
        ("Library access", settings.allow_institutional_fallback(), "OpenAthens off campus; direct/EZproxy on campus"),
        ("Manual resolver", bool(settings.resolver_template), "SFX/OpenURL fallback"),
        ("Network mode", True, f"{settings.effective_network_mode()} · {NETWORK_MODE_HELP[settings.normalized_network_mode()]}"),
    )
    return '<div class="grid">' + "".join(
        f'<div class="status"><strong>{"✓" if ready else "○"} {html.escape(name)}</strong><span class="muted">{html.escape(detail)}</span></div>'
        for name, ready, detail in entries
    ) + "</div>"


@app.get("/", response_class=HTMLResponse)
def home():
    settings = _settings()
    if settings.needs_setup():
        return RedirectResponse("/setup", status_code=307)
    issues = settings.validate()
    warning = "" if not issues else '<p class="bad">' + html.escape(" ".join(issues)) + "</p>"
    return _layout("Fetch", f"""
<h1>DOI2PDF</h1><p class="muted">One-click lawful paper retrieval for clinical and research work.</p>
<section class="card"><h2>Your retrieval routes</h2>{_route_status(settings)}</section>
{warning}<section class="card"><h2>Retrieve a paper</h2>
<form id="fetch-form" method="post" action="/fetch">
<label for="identifier">DOI, PMID, DOI URL, or exact title</label><input id="identifier" name="identifier" required autofocus placeholder="10.1186/s12984-023-01168-x">
<label for="output_dir">Save folder</label><input id="output_dir" name="output_dir" value="{html.escape(str(settings.download_dir), quote=True)}">
<details><summary>Optional Zotero filename</summary><label for="zotero_key">Zotero item key</label><input id="zotero_key" name="zotero_key" maxlength="8" placeholder="9ET75JMH"></details>
<label class="check"><input type="checkbox" name="use_institution" value="1" {"checked" if settings.allow_institutional_fallback() else ""}> Use my configured OpenAthens/EZproxy session after OA and TDM routes</label>
<button type="submit">Retrieve PDF</button></form></section>
<section class="card"><h2>Safety</h2><p>This tool uses public OA sources, official publisher APIs, and your own authorized library session. It does not bypass paywalls or share credentials. Institutional retrieval is serialized, delayed, and daily-limited.</p><p class="muted">Automating even your own authorized session can still be restricted by a publisher's or your institution's terms of service. Confirm your library's and publishers' policies permit automated retrieval before enabling institutional access, and stop if asked to by your library.</p></section>
<div id="working"><div><div class="spinner"></div><h2>Starting the live tracker…</h2><p class="muted">The progress page will show each lawful retrieval layer as it runs.</p></div></div>
<script>document.getElementById('fetch-form').addEventListener('submit',()=>{{document.getElementById('working').classList.add('show')}});</script>""")


@app.get("/setup", response_class=HTMLResponse)
def setup() -> str:
    settings = _settings()
    return _layout("Welcome", f"""
<h1>Welcome to DOI2PDF</h1><p class="muted">A short setup makes the retrieval routes work correctly. Required fields are marked; everything else can be added later.</p>
<div class="steps"><div class="step active">1 · Essentials</div><div class="step active">2 · Library</div><div class="step active">3 · Ready</div></div>
<form method="post" action="/setup">
<section class="card"><h2>1. Essential setup</h2><p>Scholarly services require a real contact email for responsible API use. It is not used to sign into your library.</p>
<label>Your contact email (required)</label><input type="email" name="DOI2PDF_CONTACT_EMAIL" value="{html.escape('' if settings.contact_email.lower() in {'you@example.org','your@email.com'} else settings.contact_email, quote=True)}" required placeholder="doctor@hospital.org">
{_application_help("unpaywall", "Why Unpaywall asks for this")}
<label>Where should PDFs be saved?</label><input name="DOWNLOAD_DIR" value="{html.escape(str(settings.download_dir), quote=True)}" placeholder="downloads"></section>
<section class="card"><h2>2. Library access (optional)</h2><p>Open-access papers work without this section. For subscribed papers, paste the prefix supplied by your own library. Never enter your library password here.</p>
{_network_mode_field(settings)}
<label>Campus IP ranges (optional)</label><input name="DOI2PDF_CAMPUS_CIDRS" value="{html.escape(','.join(settings.campus_cidrs), quote=True)}" placeholder="140.112.0.0/16"><p class="muted">Used only by Auto mode. Separate multiple CIDR ranges with commas.</p>
<label>OpenAthens redirector prefix</label><input name="OPENATHENS_REDIRECTOR_PREFIX" value="{html.escape(settings.openathens_redirector_prefix, quote=True)}" placeholder="https://go.openathens.net/redirector/YOUR-DOMAIN?url=">
<p class="muted">Usually found in your library portal or OpenAthens Redirector link generator.</p>
<label>EZproxy login prefix</label><input name="EZPROXY_PREFIX" value="{html.escape(settings.ezproxy_prefix, quote=True)}" placeholder="https://login.yourlibrary.edu/login?url=">
<label>Library resolver / SFX template</label><input name="LIBRARY_RESOLVER_TEMPLATE" value="{html.escape(settings.resolver_template, quote=True)}" placeholder="https://resolver.yourlibrary.edu/openurl?doi={{doi}}"></section>
<section class="card"><h2>3. Optional API keys</h2><p>You can skip these now. Keys are written to the local <code>.env</code>, loaded as environment variables, and never displayed back in this page.</p><details><summary>Configure optional keys</summary>
{_secret_field("PubMed API key", "PUBMED_API_KEY", bool(settings.pubmed_api_key))}
{_application_help("pubmed")}
{_secret_field("Semantic Scholar API key", "S2_API_KEY", bool(settings.semantic_scholar_api_key))}
{_application_help("semantic")}
{_secret_field("Elsevier TDM key", "ELSEVIER_TDM_KEY", bool(settings.elsevier_api_key))}
{_application_help("elsevier")}
{_secret_field("Elsevier institution token", "ELSEVIER_INSTTOKEN", bool(settings.elsevier_insttoken))}
{_secret_field("Wiley TDM token", "WILEY_TDM_TOKEN", bool(settings.wiley_tdm_token))}
{_application_help("wiley")}
{_secret_field("Springer API key", "SPRINGER_API_KEY", bool(settings.springer_api_key))}
{_application_help("springer")}</details>
<button type="submit">Save and start DOI2PDF</button></section></form>""")


@app.post("/setup", response_class=HTMLResponse)
async def save_setup(request: Request):
    form = _parse_body(await request.body())
    email = form.get("DOI2PDF_CONTACT_EMAIL", "").strip()
    candidate = Settings(
        contact_email=email,
        unpaywall_email=email,
        setup_complete=True,
        network_mode=form.get("DOI2PDF_NETWORK_MODE", "auto").strip() or "auto",
        campus_cidrs=tuple(part.strip() for part in form.get("DOI2PDF_CAMPUS_CIDRS", "").split(",") if part.strip()),
        openathens_redirector_prefix=form.get("OPENATHENS_REDIRECTOR_PREFIX", "").strip(),
        ezproxy_prefix=form.get("EZPROXY_PREFIX", "").strip(),
        resolver_template=form.get("LIBRARY_RESOLVER_TEMPLATE", "").strip(),
    )
    if candidate.validate():
        problems = "<br>".join(html.escape(issue) for issue in candidate.validate())
        return _layout("Setup problem", f'<section class="card"><h2>Please check these settings</h2><p class="bad">{problems}</p><a class="button" href="/setup">Return to setup</a></section>')
    allowed = {
        "DOI2PDF_CONTACT_EMAIL", "DOWNLOAD_DIR", "PUBMED_API_KEY", "S2_API_KEY",
        "ELSEVIER_TDM_KEY", "ELSEVIER_INSTTOKEN", "WILEY_TDM_TOKEN", "SPRINGER_API_KEY",
        "OPENATHENS_REDIRECTOR_PREFIX", "EZPROXY_PREFIX", "LIBRARY_RESOLVER_TEMPLATE", "DOI2PDF_NETWORK_MODE", "DOI2PDF_CAMPUS_CIDRS",
    }
    updates = {key: value.strip() for key, value in form.items() if key in allowed}
    updates["UNPAYWALL_EMAIL"] = email
    updates["DOI2PDF_SETUP_COMPLETE"] = "true"
    _write_env(updates)
    return RedirectResponse("/", status_code=303)


def _run_fetch_job(job_id: str, form: dict[str, str]) -> None:
    identifier = form.get("identifier", "").strip()
    output_dir = Path(form.get("output_dir", "downloads") or "downloads")
    use_institution = form.get("use_institution") == "1"
    provisional = output_dir / f".{job_id}.download.pdf"
    _job_event(job_id, {"percent": 2, "stage": "starting", "message": "Starting retrieval"}, state="running")
    try:
        client = DOI2PDF(_settings())
        result = client.fetch(identifier, provisional, use_institution, progress=lambda event: _job_event(job_id, event))
        if result.ok:
            final_path = build_pdf_path(
                output_dir,
                zotero_key=form.get("zotero_key") or None,
                doi=result.doi,
                metadata=result.metadata.get("zotero") or {},
            )
            provisional.replace(final_path)
            result.path = final_path
            file_token = _register_file(final_path)
        else:
            file_token = None
        with _JOB_LOCK:
            job = _JOBS[job_id]
            job["result"] = result
            job["file_token"] = file_token
            job["state"] = "succeeded" if result.ok else "manual_required"
            job["percent"] = 100
            job["updated_at"] = time.time()
    except Exception as exc:
        provisional.unlink(missing_ok=True)
        message = _redact(f"{type(exc).__name__}: {exc}")
        with _JOB_LOCK:
            job = _JOBS[job_id]
            job.update({"state": "failed", "percent": 100, "stage": "failed", "message": "Retrieval failed", "error": message, "updated_at": time.time()})
        _job_event(job_id, {"percent": 100, "stage": "failed", "message": "Retrieval failed", "status": type(exc).__name__}, state="failed")


def _run_login_job() -> None:
    _LOGIN_STATE.update({"state": "running", "message": "Visible Chromium is waiting for your SSO/MFA."})
    try:
        DOI2PDF(_settings()).institution.login(wait_for_console=False)
        _LOGIN_STATE.update({"state": "complete", "message": "The browser session was saved to the private profile."})
    except Exception as exc:
        _LOGIN_STATE.update({"state": "failed", "message": _redact(f"{type(exc).__name__}: {exc}")})


def _start_login_job() -> bool:
    if _LOGIN_STATE.get("state") == "running":
        return False
    threading.Thread(target=_run_login_job, daemon=True, name="doi2pdf-library-login").start()
    return True


@app.post("/fetch", response_class=HTMLResponse)
async def fetch(request: Request):
    form = _parse_body(await request.body())
    identifier = form.get("identifier", "").strip()
    if not identifier:
        return _layout("Error", '<section class="card"><p class="bad">An identifier is required.</p></section>')
    try:
        form["output_dir"] = str(_resolve_output_dir(form.get("output_dir", ""), _settings()))
    except ValueError as exc:
        return _layout("Error", f'<section class="card"><p class="bad">{html.escape(str(exc))}</p><a class="button" href="/">Back to retrieval</a></section>')
    try:
        job_id = _new_job(identifier)
    except Exception as exc:
        return _layout("Busy", f'<section class="card"><h2>Retrieval queue is full</h2><p class="bad">{html.escape(str(exc))}</p><a class="button" href="/activity">Open activity monitor</a></section>')
    threading.Thread(target=_run_fetch_job, args=(job_id, form), daemon=True, name=f"doi2pdf-{job_id[:8]}").start()
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


def _render_result(job: dict[str, Any]) -> str:
    result = job.get("result")
    if result is None:
        raise HTTPException(status_code=409, detail="Retrieval is still running")
    file_token = job.get("file_token")

    rows = "".join(
        f"<tr><td>{html.escape(attempt.layer)}</td><td>{html.escape(attempt.source)}</td>"
        f"<td>{html.escape(attempt.status)}</td><td>{html.escape(_redact(attempt.detail or ''))}</td></tr>"
        for attempt in result.attempts
    )
    if result.ok:
        summary = f'<p class="ok">PDF retrieved successfully.</p><p><strong>Saved as:</strong> <code>{html.escape(result.path.name)}</code></p><p><strong>Route:</strong> {html.escape(str(result.layer))} / {html.escape(str(result.route))} · {result.bytes:,} bytes</p><p><a class="button success" target="_blank" href="/files/{file_token}">Open PDF</a> <a class="button secondary" href="/files/{file_token}?download=1">Download a copy</a></p><p class="muted">Local folder: {html.escape(str(result.path.resolve().parent))}</p>'
    else:
        resolver = f'<p><a class="button secondary" target="_blank" href="{html.escape(result.resolver_url, quote=True)}">Open library resolver</a></p>' if result.resolver_url else ""
        summary = '<p class="bad">No automatic route produced a verified PDF.</p>' + resolver
    return _layout("Result", f'<h1>Result</h1><section class="card">{summary}<p><strong>DOI:</strong> {html.escape(result.doi)}</p></section><section class="card"><h2>Route report</h2><table><thead><tr><th>Layer</th><th>Source</th><th>Status</th><th>Detail</th></tr></thead><tbody>{rows}</tbody></table></section><a class="button" href="/">Retrieve another</a>')


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_progress(job_id: str) -> str:
    with _JOB_LOCK:
        if job_id not in _JOBS:
            raise HTTPException(status_code=404, detail="Retrieval job not found")
    return _layout("Progress", f"""
<h1>Retrieval progress</h1><p class="muted">This page updates automatically. You may also watch all jobs in <a href="/activity">Activity</a>.</p>
<section class="card"><div class="progress-track"><div id="bar" class="progress-bar"></div></div><p><strong id="percent">0%</strong> · <span id="stage">Queued</span></p><p id="message" class="muted">Waiting to start</p><p id="done"></p></section>
<section class="card"><h2>Live route log</h2><ul id="events" class="log"></ul></section>
<script>
const jobId={json.dumps(job_id)}; const seen=new Set();
function addEvent(event){{if(seen.has(event.time+'|'+event.stage+'|'+event.message+'|'+event.percent))return;seen.add(event.time+'|'+event.stage+'|'+event.message+'|'+event.percent);const li=document.createElement('li');li.textContent=`${{event.time}}  ${{event.percent}}%  [${{event.stage}}] ${{event.message}}${{event.source?' · '+event.source:''}}${{event.status?' · '+event.status:''}}`;document.getElementById('events').appendChild(li);}}
async function poll(){{const response=await fetch(`/api/jobs/${{jobId}}`,{{cache:'no-store'}});if(!response.ok)return;const job=await response.json();document.getElementById('bar').style.width=job.percent+'%';document.getElementById('percent').textContent=job.percent+'%';document.getElementById('stage').textContent=job.stage;document.getElementById('message').textContent=job.message;job.events.forEach(addEvent);if(job.result_url){{const a=document.createElement('a');a.className='button success';a.href=job.result_url;a.textContent=job.result&&job.result.ok?'Open result and PDF':'Open route report';document.getElementById('done').replaceChildren(a);return;}}if(job.state==='failed'){{document.getElementById('done').textContent=job.error||'Retrieval failed';return;}}setTimeout(poll,700);}}poll();
</script>""")


@app.get("/jobs/{job_id}/result", response_class=HTMLResponse)
def job_result(job_id: str) -> str:
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Retrieval job not found")
        return _render_result(job)


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> JSONResponse:
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Retrieval job not found")
        return JSONResponse(_job_snapshot(job))


@app.get("/api/jobs")
def jobs_status() -> JSONResponse:
    with _JOB_LOCK:
        jobs = sorted(_JOBS.values(), key=lambda item: item["created_at"], reverse=True)
        return JSONResponse({"jobs": [_job_snapshot(job) for job in jobs]})


@app.get("/activity", response_class=HTMLResponse)
def activity() -> str:
    return _layout("Activity", """
<h1>Activity monitor</h1><p class="muted">Live, in-memory retrieval status. Logs are sanitized, contain no API keys or cookies, and reset when DOI2PDF restarts.</p>
<section class="card"><table><thead><tr><th>Paper</th><th>Status</th><th>Progress</th><th>Current step</th><th></th></tr></thead><tbody id="jobs"></tbody></table><p id="empty" class="muted">No retrievals yet.</p></section>
<section class="card"><h2>Recent route events</h2><ul id="activity-events" class="log"></ul></section>
<script>
async function poll(){{const response=await fetch('/api/jobs',{{cache:'no-store'}});const data=await response.json();const body=document.getElementById('jobs');const feed=document.getElementById('activity-events');body.replaceChildren();feed.replaceChildren();document.getElementById('empty').style.display=data.jobs.length?'none':'block';const events=[];for(const job of data.jobs){{const tr=document.createElement('tr');for(const value of [job.identifier,job.state,job.percent+'%',job.message]){{const td=document.createElement('td');td.textContent=value;tr.appendChild(td);}}const td=document.createElement('td');const a=document.createElement('a');a.href='/jobs/'+job.id;a.textContent='View';td.appendChild(a);tr.appendChild(td);body.appendChild(tr);for(const event of job.events)events.push({{job,event}});}}for(const item of events.slice(-30).reverse()){{const li=document.createElement('li');li.textContent=`${{item.event.time}}  ${{item.job.identifier}}  [${{item.event.stage}}] ${{item.event.message}}`;feed.appendChild(li);}}setTimeout(poll,1000);}}poll();
</script>""")


@app.get("/acceptance", response_class=HTMLResponse)
def acceptance() -> str:
    settings = _settings()
    rows = "".join(
        f'<tr><td>{html.escape(item["publisher"])}</td><td><code>{html.escape(item["doi"])}</code>'
        f'<br>{html.escape(item["title"])}<br><a target="_blank" rel="noopener" href="{html.escape(item["source_url"], quote=True)}">Publisher/source page</a></td><td>{html.escape(item["access_class"])}</td>'
        f'<td><form method="post" action="/fetch"><input type="hidden" name="identifier" value="{html.escape(item["doi"], quote=True)}">'
        f'<input type="hidden" name="output_dir" value="{html.escape(str(settings.download_dir), quote=True)}">'
        '<input type="hidden" name="use_institution" value="1"><button type="submit">Try with my access</button></form></td></tr>'
        for item in corpus()
    )
    return _layout("Acceptance", f"""
<h1>Live acceptance set</h1><p class="muted">These are real publisher records with known OA successes, PMC edge cases, and subscription controls checked on 16 July 2026. Run them one at a time; institutional controls require your own legitimate access. This is deliberately not a bulk test.</p>
<section class="card"><table><thead><tr><th>Source</th><th>Paper</th><th>Why included</th><th>Test</th></tr></thead><tbody>{rows}</tbody></table></section>
<section class="card"><p><strong>Interpretation:</strong> subscription cases test your authorized OpenAthens/EZproxy route. OA rows should succeed without it. A PMC record may provide reusable full text without providing an article PDF; that is not evidence that Nature subscription access exists.</p></section>""")


@app.get("/routes", response_class=HTMLResponse)
def routes_page() -> str:
    settings = _settings()
    health = route_health_summary(settings.browser_profile / "access_log.jsonl")
    counts = {row["prefix"]: row for row in health["routes"]}
    rows = "".join(
        f'<tr><td><code>{html.escape(prefix)}</code></td><td>{html.escape(spec.label)}</td>'
        f'<td>{html.escape(spec.kind)}{" / headful" if spec.headful else ""}</td>'
        f'<td>{counts[prefix]["pdf"]}</td><td>{counts[prefix]["failures"]}</td></tr>'
        for prefix, spec in sorted(ROUTES.items())
    )
    warning = '<p class="bad">Rate-limit or anti-bot blocks have been recorded. Stop institutional retrieval and inspect the log summary.</p>' if health["blocks"] else '<p class="ok">No rate-limit or anti-bot block is recorded.</p>'
    return _layout("Routes", f'<h1>Publisher routes</h1><p class="muted">The complete paper-fetch publisher registry plus sanitized local success counts. No URLs, cookies, credentials, or signed links are displayed.</p><section class="card">{warning}<p>Route events: {health["route_events"]} · subscribed prefixes without a route: {html.escape(", ".join(health["subscribed_route_gaps"]) or "none")}</p><table><thead><tr><th>Prefix</th><th>Publisher</th><th>Method</th><th>PDF</th><th>Failures</th></tr></thead><tbody>{rows}</tbody></table></section>')


@app.get("/rules", response_class=HTMLResponse)
def learned_rules_page() -> str:
    settings = _settings()
    rules = RuleStore(settings.browser_profile / "learned_pdf_rules.json").list()
    rows = "".join(
        f'<tr><td>{html.escape(row["host"])}</td><td><code>{html.escape(row["selector"])}</code></td>'
        f'<td>{html.escape(row.get("source", ""))}</td><td>{html.escape(row.get("status", ""))}</td>'
        f'<td>{int(row.get("successes", 0))} / {int(row.get("failures", 0))}</td><td>'
        f'<form method="post" action="/rules/forget"><input type="hidden" name="host" value="{html.escape(row["host"], quote=True)}">'
        '<button class="secondary" type="submit">Forget host</button></form></td></tr>' for row in rules
    )
    empty = '<p class="muted">No learned selectors yet. A rule appears only after a candidate downloads a validated PDF.</p>' if not rules else ""
    return _layout("Learned rules", f'<h1>Learned PDF rules</h1><p class="muted">Only hostnames and reusable selectors are stored. Signed URLs, query strings, cookies, credentials, and page HTML are never retained.</p><section class="card">{empty}<table><thead><tr><th>Host</th><th>Selector</th><th>Source</th><th>Status</th><th>Success / failure</th><th></th></tr></thead><tbody>{rows}</tbody></table></section>')


@app.post("/rules/forget")
async def forget_learned_rules(request: Request):
    host = _parse_body(await request.body()).get("host", "")
    try:
        RuleStore(_settings().browser_profile / "learned_pdf_rules.json").forget(host)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse("/rules", status_code=303)


@app.get("/configure", response_class=HTMLResponse)
def configure() -> str:
    settings = _settings()
    return _layout("Settings", f"""
<h1>Settings</h1><p class="muted">Settings are stored in the ignored local <code>.env</code> file and loaded into DOI2PDF's environment. Saved API keys are never displayed back in this page. Never enter an OpenAthens password here.</p>
<section class="card"><form method="post" action="/configure">
<label>Contact email</label><input type="email" name="DOI2PDF_CONTACT_EMAIL" value="{html.escape(settings.contact_email, quote=True)}" required>
<label>Unpaywall email</label><input type="email" name="UNPAYWALL_EMAIL" value="{html.escape(settings.unpaywall_email, quote=True)}">
{_application_help("unpaywall")}
<label>Default PDF folder</label><input name="DOWNLOAD_DIR" value="{html.escape(str(settings.download_dir), quote=True)}">
{_secret_field("PubMed API key", "PUBMED_API_KEY", bool(settings.pubmed_api_key))}
{_application_help("pubmed")}
{_secret_field("Semantic Scholar API key", "S2_API_KEY", bool(settings.semantic_scholar_api_key))}
{_application_help("semantic")}
{_secret_field("Elsevier TDM key", "ELSEVIER_TDM_KEY", bool(settings.elsevier_api_key))}
{_application_help("elsevier")}
{_secret_field("Elsevier institution token", "ELSEVIER_INSTTOKEN", bool(settings.elsevier_insttoken))}
{_secret_field("Wiley TDM token", "WILEY_TDM_TOKEN", bool(settings.wiley_tdm_token))}
{_application_help("wiley")}
{_secret_field("Springer API key", "SPRINGER_API_KEY", bool(settings.springer_api_key))}
{_application_help("springer")}
<details><summary>Optional LLM-assisted PDF link ranking</summary><p class="muted">The LLM receives only publisher hostname, candidate text, ARIA labels, and URL paths without query strings. It never receives cookies, credentials, signed URLs, or full page HTML.</p>
<input type="hidden" name="DOI2PDF_LLM_ENABLED" value="false"><label class="check"><input type="checkbox" name="DOI2PDF_LLM_ENABLED" value="true" {"checked" if settings.llm_enabled else ""}> Enable LLM candidate ranking</label>
<label>OpenAI-compatible base URL</label><input name="DOI2PDF_LLM_BASE_URL" value="{html.escape(settings.llm_base_url, quote=True)}" placeholder="https://provider.example/v1 or http://127.0.0.1:11434/v1">
<label>Model</label><input name="DOI2PDF_LLM_MODEL" value="{html.escape(settings.llm_model, quote=True)}">
{_secret_field("LLM API key", "DOI2PDF_LLM_API_KEY", bool(settings.llm_api_key))}</details>
{_network_mode_field(settings)}
<label>Campus IP ranges (optional)</label><input name="DOI2PDF_CAMPUS_CIDRS" value="{html.escape(','.join(settings.campus_cidrs), quote=True)}" placeholder="140.112.0.0/16"><p class="muted">Used only by Auto mode. Separate multiple CIDR ranges with commas.</p>
<label>OpenAthens redirector prefix</label><input name="OPENATHENS_REDIRECTOR_PREFIX" value="{html.escape(settings.openathens_redirector_prefix, quote=True)}" placeholder="https://go.openathens.net/redirector/YOUR-DOMAIN?url=">
<label>EZproxy prefix/template</label><input name="EZPROXY_PREFIX" value="{html.escape(settings.ezproxy_prefix, quote=True)}">
<label>EZproxy publisher-host suffix</label><input name="EZPROXY_SUFFIX" value="{html.escape(settings.ezproxy_suffix, quote=True)}" placeholder="ezproxy.example.edu"><p class="muted">Optional. Enables the original publisher-specific template, metadata, and LWW/Ovid routes.</p>
<details><summary>Optional EZproxy/NetScaler form login</summary><p class="muted">For a plain login form only. OpenAthens, Shibboleth, CAPTCHA, and MFA remain an interactive visible-browser step.</p>
<label>Login URL</label><input name="LIBRARY_LOGIN_URL" value="{html.escape(settings.library_login_url, quote=True)}" placeholder="https://login.example.edu/login">
{_secret_field("Library username", "LIBRARY_USERNAME", bool(settings.library_username))}
{_secret_field("Library password", "LIBRARY_PASSWORD", bool(settings.library_password))}
<label>Username CSS selector</label><input name="LIBRARY_USER_SELECTOR" value="{html.escape(settings.library_user_selector, quote=True)}">
<label>Password CSS selector</label><input name="LIBRARY_PASSWORD_SELECTOR" value="{html.escape(settings.library_password_selector, quote=True)}">
<label>Submit CSS selector</label><input name="LIBRARY_SUBMIT_SELECTOR" value="{html.escape(settings.library_submit_selector, quote=True)}"></details>
<label>Library resolver template</label><input name="LIBRARY_RESOLVER_TEMPLATE" value="{html.escape(settings.resolver_template, quote=True)}" placeholder="https://resolver.example/openurl?doi={{doi}}">
<label>Holdings SQLite path</label><input name="HOLDINGS_DB" value="{html.escape(str(settings.holdings_db or ''), quote=True)}" placeholder="C:\\path\\holdings.sqlite">
<label>paper-radar SQLite path</label><input name="PAPER_RADAR_DB" value="{html.escape(str(settings.paper_radar_db or ''), quote=True)}" placeholder="C:\\path\\papers.sqlite">
<button type="submit">Save settings</button></form></section>
<section class="card"><h2>API connectivity</h2><p>Send one small real request to each configured provider. Results show only provider, status, and HTTP code; keys are never returned.</p><form method="post" action="/api-check"><button class="secondary" type="submit">Test configured API keys</button></form></section>
<section class="card"><h2>Library Access Assistant</h2><p>Copy one database, journal, or full-text link from your own library portal. DOI2PDF can recognize common OpenAthens redirector and EZproxy formats without opening the target or saving its article URL.</p>
<form method="post" action="/library-detect"><label>Library-provided link</label><input type="url" name="library_url" required autocomplete="off" spellcheck="false" placeholder="https://go.openathens.net/redirector/your-institution?url=...">
<button class="secondary" type="submit">Detect access settings</button></form><p class="muted">Nothing is saved until you review and apply the detected prefix or suffix.</p></section>
<section class="card"><h2>Institutional session</h2><p>Open visible Chromium and complete SSO/MFA yourself. The web request returns immediately while the browser remains available for up to three minutes; there is no terminal prompt.</p><p class="muted">This automates your own already-authorized session; it never bypasses a paywall or shares credentials. It may still be restricted by your library's or a publisher's terms of service — check before relying on it, and stop if your library asks you to.</p><p>Status: <strong>{html.escape(str(_LOGIN_STATE.get("state", "idle")))}</strong> — {html.escape(str(_LOGIN_STATE.get("message", "")))}</p><form method="post" action="/institution-login"><button class="secondary" type="submit">Open institutional login</button></form></section>""")


@app.post("/configure")
async def save_configuration(request: Request):
    allowed = {
        "DOI2PDF_CONTACT_EMAIL", "UNPAYWALL_EMAIL", "DOWNLOAD_DIR", "PUBMED_API_KEY", "S2_API_KEY",
        "ELSEVIER_TDM_KEY", "ELSEVIER_INSTTOKEN", "WILEY_TDM_TOKEN", "SPRINGER_API_KEY",
        "OPENATHENS_REDIRECTOR_PREFIX", "EZPROXY_PREFIX", "EZPROXY_SUFFIX", "LIBRARY_RESOLVER_TEMPLATE", "DOI2PDF_NETWORK_MODE", "DOI2PDF_CAMPUS_CIDRS",
        "HOLDINGS_DB", "PAPER_RADAR_DB",
        "LIBRARY_LOGIN_URL", "LIBRARY_USERNAME", "LIBRARY_PASSWORD", "LIBRARY_USER_SELECTOR",
        "LIBRARY_PASSWORD_SELECTOR", "LIBRARY_SUBMIT_SELECTOR",
        "DOI2PDF_LLM_ENABLED", "DOI2PDF_LLM_BASE_URL", "DOI2PDF_LLM_MODEL", "DOI2PDF_LLM_API_KEY",
    }
    form = _parse_body(await request.body())
    updates = {key: value.strip() for key, value in form.items() if key in allowed}
    current = _settings()
    candidate = Settings(
        contact_email=updates.get("DOI2PDF_CONTACT_EMAIL", ""),
        unpaywall_email=updates.get("UNPAYWALL_EMAIL", ""),
        setup_complete=True,
        network_mode=updates.get("DOI2PDF_NETWORK_MODE", "auto"),
        campus_cidrs=tuple(part.strip() for part in updates.get("DOI2PDF_CAMPUS_CIDRS", "").split(",") if part.strip()),
        openathens_redirector_prefix=updates.get("OPENATHENS_REDIRECTOR_PREFIX", ""),
        ezproxy_prefix=updates.get("EZPROXY_PREFIX", ""),
        ezproxy_suffix=updates.get("EZPROXY_SUFFIX", ""),
        library_login_url=updates.get("LIBRARY_LOGIN_URL", ""),
        library_username=updates.get("LIBRARY_USERNAME") or current.library_username,
        library_password=updates.get("LIBRARY_PASSWORD") or current.library_password,
        resolver_template=updates.get("LIBRARY_RESOLVER_TEMPLATE", ""),
        llm_enabled=updates.get("DOI2PDF_LLM_ENABLED", "false").lower() == "true",
        llm_base_url=updates.get("DOI2PDF_LLM_BASE_URL", ""),
        llm_model=updates.get("DOI2PDF_LLM_MODEL", ""),
        llm_api_key=updates.get("DOI2PDF_LLM_API_KEY") or current.llm_api_key,
    )
    if candidate.validate():
        problems = "<br>".join(html.escape(issue) for issue in candidate.validate())
        return _layout("Settings problem", f'<section class="card"><h2>Please check these settings</h2><p class="bad">{problems}</p><a class="button" href="/configure">Return to settings</a></section>')
    updates["DOI2PDF_SETUP_COMPLETE"] = "true"
    _write_env(updates)
    return RedirectResponse("/configure?saved=1", status_code=303)


@app.post("/api-check", response_class=HTMLResponse)
async def api_check() -> str:
    results = await run_in_threadpool(probe_all, _settings())
    rows = "".join(
        f'<tr><td>{html.escape(row["provider"])}</td><td>{"yes" if row["configured"] else "no"}</td>'
        f'<td class="{"ok" if row["ok"] else "bad"}">{html.escape(row["status"])}</td>'
        f'<td>{html.escape(str(row.get("http_status", "-")))}</td></tr>' for row in results
    )
    return _layout("API check", f'<h1>API connectivity check</h1><section class="card"><table><thead><tr><th>Provider</th><th>Configured</th><th>Result</th><th>HTTP</th></tr></thead><tbody>{rows}</tbody></table><p class="muted">A publisher key can be accepted even when this account or network is not entitled to the selected article.</p><a class="button" href="/configure">Back to settings</a></section>')


@app.post("/library-detect", response_class=HTMLResponse)
async def library_detect(request: Request) -> str:
    value = _parse_body(await request.body()).get("library_url", "")
    try:
        detection = detect_library_link(value)
    except ValueError as exc:
        return _layout("Library link not recognized", f'<section class="card"><h2>Could not recognize this link</h2><p class="bad">{html.escape(str(exc))}</p><p>No settings were changed.</p><a class="button" href="/configure">Try another link</a></section>')
    field, inferred = next(iter(detection["updates"].items()))
    return _layout("Library access detected", f'<h1>Review detected access</h1><section class="card"><p class="ok">Detected: {html.escape(detection["label"])}</p><p><strong>Source host:</strong> {html.escape(detection["host"])}</p><p><strong>Setting:</strong> <code>{html.escape(field)}</code></p><p><strong>Inferred value:</strong> <code>{html.escape(inferred)}</code></p><p class="muted">{html.escape(detection["warning"])}</p><form method="post" action="/library-detect/apply"><input type="hidden" name="field" value="{html.escape(field, quote=True)}"><input type="hidden" name="value" value="{html.escape(inferred, quote=True)}"><button type="submit" name="start_login" value="0">Apply setting</button> <button class="secondary" type="submit" name="start_login" value="1">Apply and open login</button></form><a class="button secondary" href="/configure">Cancel</a></section>')


@app.post("/library-detect/apply", response_class=HTMLResponse)
async def apply_library_detection(request: Request):
    form = _parse_body(await request.body())
    field, value = form.get("field", ""), form.get("value", "").strip()
    valid = False
    if field in {"OPENATHENS_REDIRECTOR_PREFIX", "EZPROXY_PREFIX"}:
        valid = value.startswith("https://") and value.lower().endswith("url=")
    elif field == "EZPROXY_SUFFIX":
        valid = bool(re.fullmatch(r"[A-Za-z0-9.-]+(?::\d+)?", value))
    if not valid:
        raise HTTPException(status_code=400, detail="The detected library setting is invalid.")
    _write_env({field: value})
    if form.get("start_login") == "1":
        _start_login_job()
        return _layout("Library login opened", '<section class="card"><p class="ok">The setting was saved and visible Chromium is opening.</p><p>Complete your institution\'s SSO/MFA in that browser. DOI2PDF will keep it open for up to three minutes and save the session automatically.</p><a class="button" href="/configure">Return to settings</a></section>')
    return RedirectResponse("/configure?library_detected=1", status_code=303)


@app.post("/institution-login", response_class=HTMLResponse)
def institution_login() -> str:
    started = _start_login_job()
    message = "Visible Chromium is opening. Complete SSO/MFA there; no terminal input is needed." if started else "A library login browser is already running."
    return _layout("Login browser", f'<section class="card"><p class="ok">{html.escape(message)}</p><p>The session remains open for up to three minutes and is stored only in the private browser profile.</p><a class="button" href="/configure">Back to settings</a></section>')


@app.get("/health")
def health() -> JSONResponse:
    settings = _settings()
    issues = settings.validate()
    configuration_ok = not issues
    setup_complete = settings.setup_complete
    with _JOB_LOCK:
        active_jobs = sum(job["state"] in {"queued", "running"} for job in _JOBS.values())
        recent_jobs = len(_JOBS)
    route_health = route_health_summary(settings.browser_profile / "access_log.jsonl")
    return JSONResponse({
        "ok": configuration_ok and setup_complete, "version": __version__, "issues": issues,
        "status": "ready" if configuration_ok and setup_complete else ("invalid_configuration" if issues else "setup_required"),
        "configuration_ok": configuration_ok,
        "setup_complete": setup_complete,
        "network_mode": settings.normalized_network_mode(),
        "effective_network_mode": settings.effective_network_mode(),
        "jobs": {"active": active_jobs, "recent": recent_jobs},
        "library_login": {"state": _LOGIN_STATE.get("state", "idle"), "message": _redact(_LOGIN_STATE.get("message", ""))},
        "routes": {
            "open_access": True,
            "unpaywall": bool(settings.unpaywall_email),
            "openalex": True,
            "pmc": True,
            "arxiv": True,
            "zotero_translation_server": settings.translator_enabled,
            "openathens": bool(settings.openathens_redirector_prefix),
            "ezproxy": bool(settings.ezproxy_prefix or settings.ezproxy_suffix),
            "ezproxy_suffix": bool(settings.ezproxy_suffix),
            "resolver": bool(settings.resolver_template),
            "holdings": bool(settings.holdings_db and settings.holdings_db.is_file()),
            "llm_assisted_discovery": settings.llm_enabled,
            "optional_browser": browser_capabilities(),
            "learned_rules": len(RuleStore(settings.browser_profile / "learned_pdf_rules.json").list()),
        },
        "route_health": {key: route_health[key] for key in ("route_events", "statuses", "blocks", "subscribed_route_gaps")},
    })


@app.get("/files/{token}")
def serve_file(token: str, download: bool = False):
    path = _FILES.get(token)
    if not path or not path.is_file():
        raise HTTPException(status_code=404, detail="This PDF link has expired. Retrieve the paper again.")
    disposition = "attachment" if download else "inline"
    return FileResponse(path, media_type="application/pdf", filename=path.name, content_disposition_type=disposition)


def main() -> None:
    import uvicorn

    url = "http://127.0.0.1:8765"
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")


if __name__ == "__main__":
    main()
