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
             beds: int | None = None, max_price: int | None = None):
    rows = data.get_listings(listing_type=type, search=q, beds=beds, max_price=max_price)
    return templates.TemplateResponse(
        request,
        "listings.html",
        {"listings": rows, "active_type": type or "all", "q": q or "",
         "beds": beds or "", "max_price": max_price or ""},
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


@app.get("/health")
def health():
    return JSONResponse({"status": "ok", "mode": config.mode(), "company": config.COMPANY_NAME})
