"""
FastAPI app entry point.

Routes:
  GET  /                      home (hero + featured listings)
  GET  /listings             listings index (filter by sale/rent + search)
  GET  /listings/{slug}      single listing detail + inquiry form
  GET  /about                about page
  GET  /contact              contact page + general inquiry form
  POST /inquire              handles inquiry form submissions (-> Zoho Lead)
  GET  /health               JSON health/mode check

Run:  uvicorn app.main:app --reload
"""
from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import config, data, kpi

BASE_DIR = Path(__file__).resolve().parent
# Static assets live in public/ at the project root so a CDN can serve them
# directly instead of routing 3MB of images and video through the app.
STATIC_DIR = BASE_DIR.parent / "public" / "static"

app = FastAPI(title=f"{config.COMPANY_NAME} — website")
if STATIC_DIR.is_dir():   # in production the CDN answers these before we do
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _fmt_price(value: float, currency: str = "AED", listing_type: str = "sale") -> str:
    try:
        n = f"{int(value):,}"
    except (TypeError, ValueError):
        n = str(value)
    suffix = "/yr" if listing_type == "rent" else ""
    return f"{currency} {n}{suffix}"





def _asset_version() -> str:
    """
    Cache-buster for CSS/JS.

    Browsers hold on to stylesheets hard. After a deploy the new HTML would load
    with the OLD cached stylesheet, so icons render unsized (huge), the search
    slider and hero video lose their positioning, and the page looks broken.
    Appending a hash of the file contents makes the URL change whenever the file
    changes, so a fresh copy is always fetched — and cached normally otherwise.

    On a serverless host the CSS/JS may not be inside the function bundle at all
    (the CDN serves them), so hashing them isn't possible. There we fall back to
    the deploy's git commit, which changes exactly when the assets could have.
    """
    import hashlib, os
    h = hashlib.md5()
    hashed_any = False
    for rel in ("css/styles.css", "js/site.js"):
        try:
            h.update((STATIC_DIR / rel).read_bytes())
            hashed_any = True
        except OSError:
            pass
    if hashed_any:
        return h.hexdigest()[:10]

    commit = (os.getenv("VERCEL_GIT_COMMIT_SHA")
              or os.getenv("RENDER_GIT_COMMIT")
              or os.getenv("GIT_COMMIT_SHA") or "")
    return commit[:10] if commit else "dev"


ASSET_V = _asset_version()


def _base_url(request) -> str:
    """Public base URL, honouring the proxy headers Render sets."""
    fwd_proto = request.headers.get("x-forwarded-proto")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if host:
        return f"{fwd_proto or request.url.scheme}://{host}".rstrip("/")
    return str(request.base_url).rstrip("/")


def _canonical_url(request) -> str:
    return f"{_base_url(request)}{request.url.path}"


def _fmt_area(value) -> str:
    """1340.0 -> '1,340'   |   695.56 -> '695.56'  (no ugly trailing .0)"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "0"
    if abs(v - round(v)) < 0.005:
        return f"{int(round(v)):,}"
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def _digits(phone: str) -> str:
    return "".join(c for c in (phone or "") if c.isdigit())


def _wa_link(phone: str, text: str = "") -> str:
    d = _digits(phone) or _digits(config.COMPANY_PHONE)
    import urllib.parse
    q = ("?text=" + urllib.parse.quote(text)) if text else ""
    return f"https://wa.me/{d}{q}"


# make helpers + company info available in every template
templates.env.globals.update(
    company={
        "name": config.COMPANY_NAME,
        "tagline": config.COMPANY_TAGLINE,
        "phone": config.COMPANY_PHONE,
        "email": config.COMPANY_EMAIL,
        "address": config.COMPANY_ADDRESS,
    },
    fmt_price=_fmt_price,
    fmt_area=_fmt_area,
    asset_v=ASSET_V,
    base_url=_base_url,
    canonical_url=_canonical_url,
    wa_link=_wa_link,
    mode=config.mode,
)


# ------------------------------------------------------------- edge caching
# On a serverless host each request may land on a fresh instance, so the
# in-process listings cache can't help as much as it does on a long-running
# server. Letting the CDN hold pages for a minute recovers that and more: most
# visitors are served from the edge without waking a function at all.
#
# Every page here is identical for all visitors (no logins, no per-user state),
# so shared caching is safe. stale-while-revalidate means a page that has just
# expired is still served instantly while it refreshes in the background.
_NO_CACHE_PATHS = {"/health", "/debug/zoho"}
# The KPI tracker breaks the assumption above: it has logins and shows one
# person's figures. A minute of shared caching there would hand one member's
# numbers to whoever asked next, so the whole /kpi tree opts out. Those routes
# also set no-store themselves; this is the safety net for any added later.
_NO_CACHE_PREFIXES = ("/kpi",)


@app.middleware("http")
async def cache_headers(request: Request, call_next):
    response = await call_next(request)
    if (request.method == "GET"
            and response.status_code == 200
            and request.url.path not in _NO_CACHE_PATHS
            and not request.url.path.startswith(_NO_CACHE_PREFIXES)
            and "cache-control" not in response.headers):
        response.headers["Cache-Control"] = (
            "public, max-age=0, s-maxage=60, stale-while-revalidate=300"
        )
    return response


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        request, "index.html", {"featured": data.get_featured(limit=3)}
    )


@app.get("/listings", response_class=HTMLResponse)
def listings(request: Request, type: str | None = None, q: str | None = None,
             beds: int | None = None, max_price: int | None = None,
             baths: int | None = None, min_sqft: int | None = None,
             min_price: int | None = None, status: str | None = None):
    rows = data.get_listings(listing_type=type, search=q, beds=beds,
                             max_price=max_price, baths=baths, min_sqft=min_sqft,
                             min_price=min_price, status=status)
    return templates.TemplateResponse(
        request,
        "listings.html",
        {"listings": rows, "active_type": type or "all", "q": q or "",
         "beds": beds or "", "max_price": max_price or "",
         "baths": baths or "", "min_sqft": min_sqft or "",
         "min_price": min_price or "", "status": status or ""},
    )


@app.get("/listings/{slug}", response_class=HTMLResponse)
def listing_detail(request: Request, slug: str):
    listing = data.get_listing(slug)
    if not listing:
        return templates.TemplateResponse(
            request, "not_found.html", status_code=404
        )
    return templates.TemplateResponse(
        request, "listing_detail.html", {"listing": listing}
    )


@app.get("/about", response_class=HTMLResponse)
def about(request: Request):
    return templates.TemplateResponse(request, "about.html")


@app.get("/contact", response_class=HTMLResponse)
def contact(request: Request, sent: int = 0):
    return templates.TemplateResponse(
        request, "contact.html", {"sent": bool(sent)}
    )


# ------------------------------------------------------------ form protection
# These forms write straight into the CRM, so an unprotected one fills it with
# junk. Two cheap defences that don't bother real visitors with a captcha:
#   1. a honeypot field a human never sees and never fills in
#   2. a per-IP rate limit
_SUBMITS: dict[str, list[float]] = {}
_RATE_MAX = 5           # submissions ...
_RATE_WINDOW = 600.0    # ... per IP per 10 minutes


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limited(ip: str) -> bool:
    import time
    now = time.monotonic()
    recent = [t for t in _SUBMITS.get(ip, []) if now - t < _RATE_WINDOW]
    if len(_SUBMITS) > 5000:      # crude cap so this can't grow forever
        _SUBMITS.clear()
    _SUBMITS[ip] = recent + [now]
    return len(recent) >= _RATE_MAX


@app.post("/inquire")
def inquire(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(""),
    message: str = Form(...),
    slug: str = Form(""),
    website: str = Form(""),   # honeypot — hidden from humans, bots fill it in
):
    # Bots get the same success page as everyone else; nothing is delivered.
    # Telling them they were caught just teaches them to try again.
    if website.strip():
        print(f"[inquire] honeypot triggered from {_client_ip(request)} — dropped")
    elif _rate_limited(_client_ip(request)):
        print(f"[inquire] rate limit hit for {_client_ip(request)} — dropped")
    else:
        listing = data.get_listing(slug) if slug else None
        try:
            data.create_inquiry(name, email, phone, message, listing=listing)
        except Exception as exc:  # never 500 a contact form at the visitor
            print(f"[inquire] delivery failed: {exc}")

    # back to where they came from with a success flag
    target = f"/listings/{slug}?sent=1" if slug else "/contact?sent=1"
    return RedirectResponse(target, status_code=303)


# ---------------------------------------------------------------- image proxy
# Photos uploaded by agents into Zoho's Image Upload field sit behind Zoho auth,
# so a visitor's browser can't load them directly. This route fetches the file
# server-side with our Zoho token and streams it back like a normal image.
# Results are cached in memory so we don't hit Zoho on every page view.
_IMG_CACHE: dict[str, tuple[bytes, str]] = {}
_IMG_CACHE_MAX = 200


@app.get("/img/{record_id}/{file_id}")
def property_image(record_id: str, file_id: str):
    key = f"{record_id}/{file_id}"
    hit = _IMG_CACHE.get(key)
    if hit is None:
        if not config.zoho_enabled():
            return Response(status_code=404)
        try:
            from . import zoho
            got = zoho.download_field_image(record_id, file_id)
        except Exception:
            got = None
        if not got:
            return Response(status_code=404)
        if len(_IMG_CACHE) >= _IMG_CACHE_MAX:
            _IMG_CACHE.pop(next(iter(_IMG_CACHE)), None)
        _IMG_CACHE[key] = got
        hit = got

    body, ctype = hit
    # s-maxage lets the CDN serve repeat views of the same photo without ever
    # calling this function again — important on serverless, where the in-memory
    # cache above resets whenever a new instance starts.
    return Response(content=body, media_type=ctype,
                    headers={"Cache-Control":
                             "public, max-age=86400, s-maxage=604800, immutable"})


@app.get("/debug/zoho")
def debug_zoho(key: str = ""):
    """
    Diagnostic: shows exactly what the Zoho link is doing — which module was
    found, which records are published, and why each one was tagged Buy or Rent.

    This exposes your CRM module and field names, so it is NOT public: set
    DEBUG_KEY in the environment and call /debug/zoho?key=<that value>.
    With no DEBUG_KEY set, the endpoint is off.
    """
    if not config.DEBUG_KEY:
        return JSONResponse({"error": "Diagnostics disabled. Set DEBUG_KEY to enable."},
                            status_code=404)
    if not secrets.compare_digest(key, config.DEBUG_KEY):
        return JSONResponse({"error": "Not found"}, status_code=404)
    if not config.zoho_enabled():
        return JSONResponse({"zoho_enabled": False,
                             "mode": config.mode(),
                             "hint": "No Zoho keys set in the environment."})
    from . import zoho
    return JSONResponse(zoho.diagnose())


# ---------------------------------------------------------------- KPI tracker
# Internal team page at /kpi: staff log their daily numbers, managers see the
# team. Every Supabase call happens server-side in app/kpi.py — the note at the
# top of that module explains why it is not the browser-side React original.

_KPI_HEADERS = {"Cache-Control": "no-store, private",
                "X-Robots-Tag": "noindex, nofollow"}


def _kpi_user(request: Request):
    return kpi.read_token(request.cookies.get(kpi.SESSION_COOKIE))


def _kpi_page(request: Request, ctx: dict, status_code: int = 200):
    response = templates.TemplateResponse(request, "kpi.html", ctx, status_code=status_code)
    response.headers.update(_KPI_HEADERS)
    return response


def _kpi_go(target: str):
    response = RedirectResponse(target, status_code=303)
    response.headers.update(_KPI_HEADERS)
    return response


def _kpi_link(anchor: str, **params) -> str:
    import urllib.parse
    query = {"week": anchor}
    query.update(params)
    query = {k: v for k, v in query.items() if v}
    return "/kpi?" + urllib.parse.urlencode(query) if query else "/kpi"


@app.get("/kpi", response_class=HTMLResponse)
def kpi_page(request: Request, week: str = "", member: str = "",
             tab: str = "", saved: int = 0, err: str = ""):
    if not kpi.enabled():
        return _kpi_page(request, {"configured": False})

    user = _kpi_user(request)
    if not user:
        return _kpi_page(request, {"configured": True, "user": None})

    anchor = kpi.monday_of(week or kpi.today_iso())
    is_manager = user["role"] == "manager"
    tab = "mine" if tab == "mine" else "team"
    viewing = member.strip() if (is_manager and member.strip()) else ""

    ctx = {
        "configured": True, "user": user, "kpis": kpi.KPIS, "anchor": anchor,
        "tab": tab, "viewing": viewing, "saved": bool(saved),
        "week_label": kpi.fmt_day(anchor), "today_label": kpi.fmt_day(kpi.today_iso()),
        "url_prev": _kpi_link(kpi.shift_week(anchor, -1), member=viewing, tab=tab),
        "url_next": _kpi_link(kpi.shift_week(anchor, 1), member=viewing, tab=tab),
        "url_this_week": _kpi_link(kpi.monday_of(kpi.today_iso()), member=viewing, tab=tab),
        "url_team": _kpi_link(anchor),
        "url_mine": _kpi_link(anchor, tab="mine"),
        "error": "Couldn't save those numbers — try again." if err == "save" else "",
    }

    # A manager on the team tab needs everyone; anyone else needs one person.
    # Widen the query to cover the displayed week as well as the month, since a
    # week at a month boundary reaches into the neighbouring one.
    days = kpi.week_dates(anchor)
    month_start, month_end = kpi.month_bounds(anchor)
    start, end = min(days[0], month_start), max(days[-1], month_end)
    only = viewing or (None if (is_manager and tab == "team") else user["name"])

    try:
        rows = kpi.fetch_entries(start, end, member=only)
        members = kpi.list_members() if only is None else []
    except Exception as exc:
        print(f"[kpi] load failed: {exc}")
        ctx["error"] = "Couldn't reach the database just now. Refresh to try again."
        rows, members = [], []

    if only is None:
        ctx.update(view="team",
                   cards=[dict(c, url=_kpi_link(anchor, member=c["name"]))
                          for c in kpi.team_cards(rows, members, anchor)])
    else:
        ctx.update(view="member",
                   report=kpi.member_report(rows, only, anchor),
                   can_edit=(only == user["name"]))
    return _kpi_page(request, ctx)


@app.post("/kpi/login")
def kpi_login(request: Request, name: str = Form(""), password: str = Form("")):
    if not kpi.enabled():
        return _kpi_page(request, {"configured": False})

    ip = _client_ip(request)
    if kpi.login_blocked(ip):
        return _kpi_page(request, {"configured": True, "user": None,
                                   "error": "Too many attempts. Wait a few minutes."},
                         status_code=429)
    try:
        user = kpi.authenticate(name, password)
    except Exception:
        return _kpi_page(request, {"configured": True, "user": None,
                                   "error": "Couldn't reach the database. Try again."},
                         status_code=503)
    if not user:
        kpi.note_login_failure(ip)
        # One message for both cases: naming which half was wrong would let
        # anyone confirm who works here.
        return _kpi_page(request, {"configured": True, "user": None,
                                   "error": "Wrong name or password."},
                         status_code=401)

    response = _kpi_go("/kpi")
    response.set_cookie(
        kpi.SESSION_COOKIE, kpi.make_token(user["name"], user["role"]),
        max_age=kpi.SESSION_HOURS * 3600, httponly=True, samesite="lax",
        secure=_base_url(request).startswith("https://"), path="/kpi",
    )
    return response


@app.post("/kpi/logout")
def kpi_logout():
    response = _kpi_go("/kpi")
    response.delete_cookie(kpi.SESSION_COOKIE, path="/kpi")
    return response


@app.post("/kpi/save")
async def kpi_save(request: Request):
    """Always writes the signed-in person's own row — never anyone else's."""
    user = _kpi_user(request) if kpi.enabled() else None
    if not user:
        return _kpi_go("/kpi")

    form = await request.form()
    anchor = kpi.monday_of(str(form.get("week") or kpi.today_iso()))
    tab = "mine" if form.get("tab") == "mine" else ""
    try:
        kpi.save_entry(user["name"], kpi.today_iso(),
                       {k["key"]: form.get(k["key"], "") for k in kpi.KPIS})
    except Exception as exc:
        print(f"[kpi] save failed: {exc}")
        return _kpi_go(_kpi_link(anchor, tab=tab, err="save"))
    return _kpi_go(_kpi_link(anchor, tab=tab, saved="1"))


@app.get("/robots.txt")
def robots(request: Request):
    body = f"User-agent: *\nAllow: /\nSitemap: {_base_url(request)}/sitemap.xml\n"
    return Response(content=body, media_type="text/plain")


@app.get("/site.webmanifest")
def webmanifest():
    return JSONResponse({
        "name": config.COMPANY_NAME,
        "short_name": config.COMPANY_NAME,
        "icons": [{"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png"}],
        "theme_color": "#0A463A",
        "background_color": "#ffffff",
        "display": "standalone",
    })


@app.get("/sitemap.xml")
def sitemap(request: Request):
    base = _base_url(request)
    urls = [f"{base}/", f"{base}/listings", f"{base}/about", f"{base}/contact"]
    try:
        for row in data.get_listings():
            urls.append(f"{base}/listings/{row['slug']}")
    except Exception:
        pass
    items = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           f"{items}</urlset>")
    return Response(content=xml, media_type="application/xml")


@app.get("/health")
def health():
    return JSONResponse({"status": "ok", "mode": config.mode(), "company": config.COMPANY_NAME})
