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
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import config, content, data, kpi, prose, referrals, seo

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

templates.env.globals.update(cfg=config, seo=seo, fill=content.fill,
                             fmt_date=content.fmt_date)
templates.env.filters["md"] = prose.render


def _render(request: Request, name: str, page: dict, status_code: int = 200, **ctx):
    """Every public page goes through here, so every page gets the same SEO
    treatment: its own title and description, a canonical URL, an Open Graph
    image, and JSON-LD built by seo.py — the organisation, the breadcrumb trail
    and whatever the page adds. Nothing is hand-written in a template."""
    base = _base_url(request)
    page = dict(page)
    crumbs = page.get("crumbs") or []
    nodes = [seo.organisation(base)]
    if crumbs:
        nodes.append(seo.breadcrumbs(base, crumbs))
    nodes += [n for n in (page.get("ld") or []) if n]
    page["ld_json"] = [seo.render(n) for n in nodes]
    og = page.get("og_image") or "/static/hero/hero1.jpg"
    page["og_image_abs"] = og if str(og).startswith("http") else f"{base}{og}"
    page["canonical_abs"] = (f"{base}{page['canonical']}" if page.get("canonical")
                             else _canonical_url(request))
    return templates.TemplateResponse(
        request, name, {"page": page, "t": content.site(), **ctx}, status_code=status_code)


def _not_found(request: Request):
    t = content.site()
    return _render(request, "not_found.html", {
        "title": t.not_found.title, "description": t.not_found.body,
        "crumbs": [(t.breadcrumbs.home, "/")], "noindex": True,
    }, status_code=404)


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
    t = content.site()
    return _render(request, "index.html", {
        "title": t.home.title, "description": t.home.meta_description,
        "canonical": "/", "crumbs": [(t.breadcrumbs.home, "/")],
    }, featured=data.get_featured(limit=3),
        launches=content.projects("live"),          # the strip hides itself when empty
        area_guides=content.areas(),
        latest_insights=content.insights()[:3])


@app.get("/listings", response_class=HTMLResponse)
def listings(request: Request, type: str | None = None, q: str | None = None,
             beds: int | None = None, max_price: int | None = None,
             baths: int | None = None, min_sqft: int | None = None,
             min_price: int | None = None, status: str | None = None):
    rows = data.get_listings(listing_type=type, search=q, beds=beds,
                             max_price=max_price, baths=baths, min_sqft=min_sqft,
                             min_price=min_price, status=status)
    t = content.site()
    kind = type if type in ("sale", "rent") else "all"
    # Every filtered or searched variant points search engines at the plain
    # sale / rent / all URL, so a hundred filter combinations don't compete
    # with each other as near-duplicate pages.
    canonical = f"/listings?type={kind}" if kind != "all" else "/listings"
    crumbs = [(t.breadcrumbs.home, "/"), (t.breadcrumbs.listings, "/listings")]
    if kind != "all":
        crumbs.append((t.listings.get(f"h1_{kind}"), canonical))
    return _render(request, "listings.html", {
        "title": t.listings.get(f"title_{kind}"),
        "description": t.listings.get(f"desc_{kind}"),
        "h1": t.listings.get(f"h1_{kind}"),
        "canonical": canonical, "crumbs": crumbs,
    }, listings=rows, active_type=type or "all", q=q or "",
        beds=beds or "", max_price=max_price or "", baths=baths or "",
        min_sqft=min_sqft or "", min_price=min_price or "", status=status or "")


@app.get("/listings/{slug}", response_class=HTMLResponse)
def listing_detail(request: Request, slug: str):
    listing = data.get_listing(slug)
    if not listing:
        return _not_found(request)
    t = content.site()
    base = _base_url(request)
    path = f"/listings/{slug}"
    h1 = seo.listing_h1(listing)
    deal = "/listings?type=rent" if listing.get("type") == "rent" else "/listings?type=sale"
    first = (listing.get("images") or [""])[0]
    return _render(request, "listing_detail.html", {
        "title": seo.listing_title(listing),
        "description": seo.listing_description(listing),
        "canonical": path, "og_image": first or None,
        "crumbs": [(t.breadcrumbs.home, "/"), (t.breadcrumbs.listings, deal), (h1, path)],
        "ld": [seo.listing_node(listing, base, f"{base}{path}")],
    }, listing=listing, h1=h1, area_guide=content.area_for_listing(listing))


@app.get("/about", response_class=HTMLResponse)
def about(request: Request):
    t = content.site()
    return _render(request, "about.html", {
        "title": t.about.title, "description": t.about.meta_description,
        "canonical": "/about",
        "crumbs": [(t.breadcrumbs.home, "/"), (t.breadcrumbs.about, "/about")],
    }, area_guides=content.areas())


@app.get("/contact", response_class=HTMLResponse)
def contact(request: Request, sent: int = 0):
    t = content.site()
    return _render(request, "contact.html", {
        "title": t.contact.title, "description": t.contact.meta_description,
        "canonical": "/contact",
        "crumbs": [(t.breadcrumbs.home, "/"), (t.breadcrumbs.contact, "/contact")],
    }, sent=bool(sent))


# -------------------------------------------------------------- new launches
@app.get("/projects", response_class=HTMLResponse)
def projects_index(request: Request):
    t = content.site()
    grouped: dict[str, list] = {}
    for proj in content.projects("live"):        # closed launches are not listed
        grouped.setdefault(proj.get("emirate") or "Other", []).append(proj)
    return _render(request, "projects_index.html", {
        "title": t.projects.title, "description": t.projects.meta_description,
        "canonical": "/projects",
        "crumbs": [(t.breadcrumbs.home, "/"), (t.breadcrumbs.projects, "/projects")],
    }, grouped=grouped)


@app.get("/projects/{slug}", response_class=HTMLResponse)
def project_page(request: Request, slug: str, sent: int = 0):
    proj = content.get("projects", slug)
    if not proj:
        return _not_found(request)
    t = content.site()
    path = f"/projects/{slug}"
    closed = (proj.get("status") or "live").lower() == "closed"
    guide = content.get("areas", proj.get("area_slug") or "")

    alt_projects, alt_listings = [], []
    if closed:
        # A closed launch keeps its page — and whatever ranking it earned — but
        # sends visitors to what's actually for sale nearby.
        alt_projects = [x for x in content.live_projects_in(area_slug=proj.get("area_slug", ""))
                        if x["slug"] != slug]
        if not alt_projects:
            alt_projects = [x for x in content.live_projects_in(emirate=proj.get("emirate", ""))
                            if x["slug"] != slug]
        rows = data.get_listings()
        if guide:
            alt_listings = content.listings_in_area(guide, rows, limit=3)
        if not alt_listings:
            em = str(proj.get("emirate", "")).lower()
            alt_listings = [r for r in rows if em and em in
                            f"{r.get('location', '')} {r.get('community', '')}".lower()][:3]

    return _render(request, "project.html", {
        "title": proj.get("title"), "description": proj.get("meta_description"),
        "canonical": path, "og_image": proj.get("og_image"),
        "crumbs": [(t.breadcrumbs.home, "/"), (t.breadcrumbs.projects, "/projects"),
                   (proj.get("name"), path)],
        "ld": [seo.faq_node(proj.get("faq") or [])],
    }, p=proj, closed=closed, guide=guide, sent=bool(sent),
        alt_projects=alt_projects, alt_listings=alt_listings)


# --------------------------------------------------------------- area guides
@app.get("/areas", response_class=HTMLResponse)
def areas_index(request: Request):
    t = content.site()
    return _render(request, "areas_index.html", {
        "title": t.areas.title, "description": t.areas.meta_description,
        "canonical": "/areas",
        "crumbs": [(t.breadcrumbs.home, "/"), (t.breadcrumbs.areas, "/areas")],
    }, grouped=content.areas_by_emirate())


@app.get("/areas/{slug}", response_class=HTMLResponse)
def area_page(request: Request, slug: str):
    area = content.get("areas", slug)
    if not area:
        return _not_found(request)
    t = content.site()
    path = f"/areas/{slug}"
    return _render(request, "area.html", {
        "title": area.get("title"), "description": area.get("meta_description"),
        "canonical": path, "og_image": area.get("og_image"),
        "crumbs": [(t.breadcrumbs.home, "/"), (t.breadcrumbs.areas, "/areas"),
                   (area.get("area"), path)],
        "ld": [seo.faq_node(area.get("faq") or [])],
    }, a=area,
        h1=content.fill(t.areas.h1_pattern, area=area.get("area"), emirate=area.get("emirate")),
        projects=content.live_projects_in(area_slug=slug),
        area_listings=content.listings_in_area(area, data.get_listings()),
        related=content.related_insights(slug))


# ------------------------------------------------------------------ insights
@app.get("/insights", response_class=HTMLResponse)
def insights_index(request: Request):
    t = content.site()
    return _render(request, "insights_index.html", {
        "title": t.insights.title, "description": t.insights.meta_description,
        "canonical": "/insights",
        "crumbs": [(t.breadcrumbs.home, "/"), (t.breadcrumbs.insights, "/insights")],
    }, articles=content.insights())


@app.get("/insights/{slug}", response_class=HTMLResponse)
def insight_page(request: Request, slug: str):
    art = content.get("insights", slug)
    if not art:
        return _not_found(request)
    t = content.site()
    base = _base_url(request)
    path = f"/insights/{slug}"
    who = content.member(art.get("author") or "") or {}
    author = ({"name": who.get("name"), "role": who.get("role"),
               "url": f"/team#{who.get('slug')}"} if who else {})
    return _render(request, "insight.html", {
        "title": art.get("title"), "description": art.get("meta_description"),
        "canonical": path, "og_image": art.get("og_image"),
        "crumbs": [(t.breadcrumbs.home, "/"), (t.breadcrumbs.insights, "/insights"),
                   (art.get("h1"), path)],
        "ld": [seo.article_node(dict(art, author=author), base, f"{base}{path}"),
               seo.faq_node(art.get("faq") or [])],
    }, art=art, author=author,
        related_areas=[x for x in (content.get("areas", s) for s in art.get("areas") or []) if x],
        more=[x for x in content.insights() if x["slug"] != slug][:3])


# ---------------------------------------------------------------------- team
@app.get("/team", response_class=HTMLResponse)
def team_page(request: Request):
    t = content.site()
    base = _base_url(request)
    members = content.team()
    return _render(request, "team.html", {
        "title": t.team.title, "description": t.team.meta_description,
        "canonical": "/team",
        "crumbs": [(t.breadcrumbs.home, "/"), (t.breadcrumbs.team, "/team")],
        "ld": [{"@context": "https://schema.org",
                "@graph": [seo.person_node(m, base) for m in members]}] if members else [],
    }, members=members)


@app.exception_handler(StarletteHTTPException)
async def _http_errors(request: Request, exc: StarletteHTTPException):
    """Unknown URLs get a real page with ways back into the site instead of
    FastAPI's bare {"detail": "Not Found"}. Other errors keep the default."""
    if exc.status_code == 404:
        return _not_found(request)
    return await http_exception_handler(request, exc)


if config.INDEXNOW_KEY:
    @app.get(f"/{config.INDEXNOW_KEY}.txt", include_in_schema=False)
    def indexnow_key():
        """IndexNow (Bing, Yandex) checks this file to confirm a ping really
        came from this site. The key is public by design."""
        return Response(config.INDEXNOW_KEY, media_type="text/plain")


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
    message: str = Form(""),
    slug: str = Form(""),
    project: str = Form(""),     # a /projects page form
    unit_type: str = Form(""),
    budget: str = Form(""),
    purpose: str = Form(""),
    website: str = Form(""),   # honeypot — hidden from humans, bots fill it in
):
    proj = content.get("projects", project.strip()) if project.strip() else None
    # The project form's dropdowns go at the top of the lead so the agent sees
    # what they're asking about before reading anything else.
    details = [f"{label}: {value.strip()[:80]}"
               for label, value in (("Unit type", unit_type), ("Budget", budget),
                                    ("Purpose", purpose)) if value.strip()]
    body = "\n".join(details + ([message.strip()] if message.strip() else [])) or "(no message)"

    # Bots get the same success page as everyone else; nothing is delivered.
    # Telling them they were caught just teaches them to try again.
    if website.strip():
        print(f"[inquire] honeypot triggered from {_client_ip(request)} — dropped")
    elif _rate_limited(_client_ip(request)):
        print(f"[inquire] rate limit hit for {_client_ip(request)} — dropped")
    else:
        listing = data.get_listing(slug) if slug else None
        if listing is None and proj:
            # Same path as a listing enquiry: the project name becomes the
            # "[Re: …]" line in the Zoho lead's description.
            listing = {"title": proj.get("name", ""), "slug": ""}
        try:
            data.create_inquiry(name, email, phone, body, listing=listing,
                                referral=referrals.from_request(request))
        except Exception as exc:  # never 500 a contact form at the visitor
            print(f"[inquire] delivery failed: {exc}")

    # back to where they came from with a success flag
    if proj:
        target = f"/projects/{proj['slug']}?sent=1#enquire"
    elif slug:
        target = f"/listings/{slug}?sent=1"
    else:
        target = "/contact?sent=1"
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


# ------------------------------------------------------------ personal links
# corespaces.info/kassim etc. — see app/referrals.py. Each one remembers whose
# link it was and shows the normal home page. Registered one route per person
# (not a catch-all) so every other unknown URL still 404s exactly as before.
def _referral_landing(slug: str):
    def landing(request: Request):
        response = RedirectResponse("/", status_code=302)
        response.set_cookie(
            referrals.COOKIE, slug, max_age=referrals.COOKIE_DAYS * 86400,
            httponly=True, samesite="lax", path="/",
            secure=_base_url(request).startswith("https://"),
        )
        # a shared cache must never hand one person's tag to the next visitor
        response.headers["Cache-Control"] = "no-store"
        return response
    landing.__name__ = f"referral_{slug}"
    return landing


for _slug in referrals.TEAM:
    # lower-case plus Capitalised: bios get typed both ways
    for _path in {f"/{_slug}", f"/{_slug.capitalize()}"}:
        app.add_api_route(_path, _referral_landing(_slug), methods=["GET"],
                          include_in_schema=False)


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
    """Built from what actually exists: every content file adds its page, so
    new area guides, insights and projects appear here with no code change, and
    nothing is listed before it has a page. Closed projects stay in — their
    pages stay up."""
    from xml.sax.saxutils import escape
    base = _base_url(request)
    urls: list[tuple[str, str]] = [
        ("/", ""), ("/listings", ""), ("/listings?type=sale", ""),
        ("/listings?type=rent", ""), ("/about", ""), ("/contact", ""), ("/team", ""),
    ]
    for kind, index in (("projects", "/projects"), ("areas", "/areas"),
                        ("insights", "/insights")):
        items = content.all_of(kind)
        if items:
            urls.append((index, ""))
        for item in items:
            urls.append((f"{index}/{item['slug']}", str(item.get("updated") or "")[:10]))
    try:
        for row in data.get_listings():
            urls.append((f"/listings/{row['slug']}", ""))
    except Exception:
        pass
    items = "".join(
        f"<url><loc>{escape(base + path)}</loc>"
        + (f"<lastmod>{lastmod}</lastmod>" if lastmod else "") + "</url>"
        for path, lastmod in urls)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           f"{items}</urlset>")
    return Response(content=xml, media_type="application/xml")


@app.get("/health")
def health():
    return JSONResponse({"status": "ok", "mode": config.mode(), "company": config.COMPANY_NAME})
