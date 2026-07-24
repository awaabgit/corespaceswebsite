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

from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import config, data

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title=f"{config.COMPANY_NAME} — website")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _fmt_price(value: float, currency: str = "AED", listing_type: str = "sale") -> str:
    try:
        n = f"{int(value):,}"
    except (TypeError, ValueError):
        n = str(value)
    suffix = "/yr" if listing_type == "rent" else ""
    return f"{currency} {n}{suffix}"




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
    base_url=_base_url,
    canonical_url=_canonical_url,
    wa_link=_wa_link,
    mode=config.mode,
)


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


@app.post("/inquire")
def inquire(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(""),
    message: str = Form(...),
    slug: str = Form(""),
):
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
    return Response(content=body, media_type=ctype,
                    headers={"Cache-Control": "public, max-age=86400"})


@app.get("/debug/zoho")
def debug_zoho():
    """Diagnostic: shows exactly what the Zoho link is doing. Safe to leave on."""
    if not config.zoho_enabled():
        return JSONResponse({"zoho_enabled": False,
                             "mode": config.mode(),
                             "hint": "No Zoho keys set in the environment."})
    from . import zoho
    return JSONResponse(zoho.diagnose())


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
