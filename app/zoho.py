"""
Zoho CRM integration.

Two jobs:
  - fetch_properties(): pull listing records from your custom "Properties" module.
    Used by scripts/sync_zoho_to_supabase.py (and by zoho-direct mode for testing).
  - create_lead(): push a website inquiry into Zoho's Leads module.

Auth model (set up once in the FINISH phase — steps in README + zoho/oauth_setup.md):
  You register a self-client in the Zoho API console, do a one-time grant, and
  exchange it for a long-lived REFRESH TOKEN. We store the refresh token in .env
  and exchange it for a short-lived (1h) access token on demand. No user login,
  no token expiry headaches.

Everything here is lazy: nothing runs and httpx isn't even called unless Zoho
creds are present, so the app still imports and runs fine in mock mode.
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from . import config

# simple in-process access-token cache: {"token": str, "expires_at": float}
_token_cache: dict[str, Any] = {"token": None, "expires_at": 0.0}


def _get_access_token() -> str:
    """Exchange the refresh token for an access token, cached until ~1 min before expiry."""
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"]:
        return _token_cache["token"]

    url = f"{config.ZOHO_ACCOUNTS_HOST}/oauth/v2/token"
    params = {
        "refresh_token": config.ZOHO_REFRESH_TOKEN,
        "client_id": config.ZOHO_CLIENT_ID,
        "client_secret": config.ZOHO_CLIENT_SECRET,
        "grant_type": "refresh_token",
    }
    resp = httpx.post(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if "access_token" not in data:
        raise RuntimeError(f"Zoho token error: {data}")
    _token_cache["token"] = data["access_token"]
    # Zoho access tokens last 3600s; refresh a minute early to be safe.
    _token_cache["expires_at"] = now + int(data.get("expires_in", 3600)) - 60
    return _token_cache["token"]


def _headers() -> dict[str, str]:
    return {"Authorization": f"Zoho-oauthtoken {_get_access_token()}"}


def fetch_properties() -> list[dict[str, Any]]:
    """
    Pull all published listings from the custom Properties module and normalise
    them into the app's internal listing shape (same keys as mock_data).

    The field API names below (Title, Price, Bedrooms, ...) must match what you
    create in Zoho — see zoho/properties_module_schema.md. Adjust names there and
    here together if you rename a field.
    """
    module = config.ZOHO_PROPERTIES_MODULE
    base = f"{config.ZOHO_API_HOST}/crm/v2/{module}"
    listings: list[dict[str, Any]] = []
    page = 1
    with httpx.Client(timeout=60) as client:
        while True:
            resp = client.get(
                base,
                headers=_headers(),
                params={"page": page, "per_page": 200},
            )
            if resp.status_code == 204:  # no content / no records
                break
            resp.raise_for_status()
            payload = resp.json()
            for rec in payload.get("data", []):
                if not _is_published(rec):
                    continue
                listings.append(_normalise(rec))
            info = payload.get("info", {})
            if not info.get("more_records"):
                break
            page += 1
    return listings


def _pick(rec: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """
    Return the first present, non-empty field among several possible API names.
    Zoho auto-generates API names from labels, so 'Listing Type' might become
    Listing_Type, Listing_Type1, or listing_type depending on history. Trying
    several names means the connection works without us hand-matching each one.
    Matching is case-insensitive on the record's keys.
    """
    lower = {k.lower(): v for k, v in rec.items()}
    for k in keys:
        v = lower.get(k.lower())
        if v not in (None, "", []):
            return v
    return default


def _images(rec: dict[str, Any]) -> list[str]:
    """
    Read listing photos from an 'Image URLs' field (multi-line). For the demo,
    agents paste one image URL per line (or comma-separated) — no Supabase needed.
    If a list was already provided (sync path), use it as-is.
    """
    raw = _pick(rec, "Image_URLs", "Image_URL", "Images", "Photos", default="")
    if isinstance(raw, list):
        return [str(u).strip() for u in raw if str(u).strip()]
    if not raw:
        return []
    parts = str(raw).replace(",", "\n").splitlines()
    return [p.strip() for p in parts if p.strip().startswith("http")]


def _amenities(rec: dict[str, Any]) -> list[str]:
    """Read an 'Amenities' field (multi-line or comma-separated) into a list."""
    raw = _pick(rec, "Amenities", "Amenity", default="")
    if isinstance(raw, list):
        return [str(a).strip() for a in raw if str(a).strip()]
    if not raw:
        return []
    parts = str(raw).replace(",", "\n").splitlines()
    return [p.strip() for p in parts if p.strip()]


def _is_published(rec: dict[str, Any]) -> bool:
    # Checkbox controlling what's public — tolerate label variants.
    return bool(_pick(rec, "Publish_to_Web", "Publish_to_web", "publish_to_web", default=False))


def _normalise(rec: dict[str, Any]) -> dict[str, Any]:
    title = _pick(rec, "Name", "Title", default="Untitled listing")
    ltype = str(_pick(rec, "Listing_Type", "Listing_Type1", "listing_type", default="sale")).lower()
    if ltype not in ("sale", "rent"):
        ltype = "rent" if "rent" in ltype else "sale"
    return {
        "id": str(rec.get("id")),
        "slug": _pick(rec, "Slug") or _slugify(f"{title}-{rec.get('id')}"),
        "title": title,
        "type": ltype,
        "price": _num(_pick(rec, "Price")),
        "currency": _pick(rec, "Currency_Type", "Currency", default="AED"),
        "beds": int(_num(_pick(rec, "Bedrooms"))),
        "baths": int(_num(_pick(rec, "Bathrooms"))),
        "area_sqft": int(_num(_pick(rec, "Area_Sqft", "Area_sqft", "Area"))),
        "location": _pick(rec, "Location", default=""),
        "community": _pick(rec, "Community", default=""),
        "status": str(_pick(rec, "Status", default="available")).lower(),
        "featured": bool(_pick(rec, "Featured", default=False)),
        "description": _pick(rec, "Description", default=""),
        "images": _images(rec),
        "amenities": _amenities(rec),
        "agent_name": _pick(rec, "Agent_Name", "Agent_line", default=""),
        "agent_phone": _pick(rec, "Agent_Phone", default=""),
        "_zoho_id": str(rec.get("id")),
    }


def fetch_attachment_ids(record_id: str) -> list[str]:
    """Return attachment IDs for a Properties record (used by the image re-host step)."""
    url = f"{config.ZOHO_API_HOST}/crm/v2/{config.ZOHO_PROPERTIES_MODULE}/{record_id}/Attachments"
    with httpx.Client(timeout=60) as client:
        resp = client.get(url, headers=_headers())
        if resp.status_code == 204:
            return []
        resp.raise_for_status()
        return [str(a["id"]) for a in resp.json().get("data", [])]


def download_attachment(record_id: str, attachment_id: str) -> bytes:
    url = (
        f"{config.ZOHO_API_HOST}/crm/v2/{config.ZOHO_PROPERTIES_MODULE}"
        f"/{record_id}/Attachments/{attachment_id}"
    )
    with httpx.Client(timeout=120) as client:
        resp = client.get(url, headers=_headers())
        resp.raise_for_status()
        return resp.content


def create_lead(name: str, email: str, phone: str, message: str, listing_title: str = "") -> dict[str, Any]:
    """Create a Lead in Zoho from a website inquiry."""
    url = f"{config.ZOHO_API_HOST}/crm/v2/Leads"
    last_name = name.strip() or "Website Lead"
    description = message
    if listing_title:
        description = f"[Re: {listing_title}]\n\n{message}"
    body = {
        "data": [
            {
                "Last_Name": last_name,
                "Email": email,
                "Phone": phone,
                "Lead_Source": "Website",
                "Description": description,
            }
        ]
    }
    with httpx.Client(timeout=30) as client:
        resp = client.post(url, headers=_headers(), json=body)
        resp.raise_for_status()
        return resp.json()


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _slugify(text: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in text)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")
