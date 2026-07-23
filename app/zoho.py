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

import re
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


def _upload_field_images(rec: dict[str, Any]) -> list[str]:
    """
    Read photos from a Zoho IMAGE UPLOAD field (agents upload from phone/computer).

    Zoho returns such a field as a list of dicts, e.g.
        [{"File_Id__s": "abc123", "File_Name__s": "front.jpg", ...}, ...]

    Those files sit behind Zoho auth, so a browser can't load them directly.
    We turn each into a URL on OUR site — /img/<record_id>/<file_id> — which the
    app fetches server-side with the Zoho token and streams back (see app/main.py).
    """
    raw = _pick(rec, "Property_Photos", "Property_Photo", "Image_Upload_1",
                "Photos_Upload", "Images_Upload", default=None)
    rid = str(rec.get("id") or "")
    if not raw or not rid:
        return []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []

    out: list[str] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        fid = (item.get("File_Id__s") or item.get("file_Id__s")
               or item.get("attachment_Id") or item.get("id"))
        if fid:
            out.append(f"/img/{rid}/{fid}")
    return out


def _images(rec: dict[str, Any]) -> list[str]:
    """
    Listing photos, from either source:
      1. the Image Upload field  -> proxied through our own /img/... route
      2. an 'Image URLs' text field (one link per line) -> used as-is
    Uploads win when both exist. A list already provided (sync path) is used as-is.
    """
    uploaded = _upload_field_images(rec)
    if uploaded:
        return uploaded

    raw = _pick(rec, "Image_URLs", "Image_URL", "Images", "Photos", default="")
    if isinstance(raw, list):
        return [str(u).strip() for u in raw if str(u).strip()]
    if not raw:
        return []
    parts = str(raw).replace(",", "\n").splitlines()
    return [p.strip() for p in parts if p.strip().startswith("http")]


def download_field_image(record_id: str, file_id: str) -> tuple[bytes, str] | None:
    """
    Fetch one uploaded image from Zoho using the server's OAuth token.
    Returns (bytes, content_type) or None.

    Zoho's download path for image-upload fields has moved between API versions,
    so we try the known endpoints in order and use whichever answers.
    """
    module = config.ZOHO_PROPERTIES_MODULE
    host = config.ZOHO_API_HOST
    candidates = [
        (f"{host}/crm/v8/{module}/{record_id}/actions/download_fields_attachment",
         {"fields_attachment_id": file_id}),
        (f"{host}/crm/v7/{module}/{record_id}/actions/download_fields_attachment",
         {"fields_attachment_id": file_id}),
        (f"{host}/crm/v2/{module}/{record_id}/actions/download_fields_attachment",
         {"fields_attachment_id": file_id}),
        (f"{host}/crm/v2/{module}/{record_id}/Attachments/{file_id}", None),
    ]
    try:
        headers = _headers()
    except Exception:
        return None

    with httpx.Client(timeout=45, follow_redirects=True) as client:
        for url, params in candidates:
            try:
                resp = client.get(url, headers=headers, params=params)
            except Exception:
                continue
            ctype = resp.headers.get("content-type", "")
            if resp.status_code == 200 and resp.content and "json" not in ctype:
                return resp.content, (ctype or "image/jpeg")
    return None


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
    """
    A listing is public when the agent ticks 'Publish to Web' AND the status is
    still live. Sold / Off Market are hidden automatically, so a sold property
    never lingers on the site because someone forgot to untick the box.
    """
    if not bool(_pick(rec, "Publish_to_Web", "Publish_to_web", "publish_to_web", default=False)):
        return False
    status = str(_pick(rec, "Status", default="") or "").lower()
    if "sold" in status or "off market" in status or "off-market" in status:
        return False
    return True


def _split_agent(rec: dict[str, Any]) -> tuple[str, str]:
    """
    'Agent Contact' holds name + phone in one field, e.g. "Sara - +971 50 123 4567".
    Split it into (name, phone). Falls back to the older separate fields.
    """
    name = _pick(rec, "Agent_Name", "Agent_line", default="")
    phone = _pick(rec, "Agent_Phone", default="")
    if name or phone:
        return str(name), str(phone)

    raw = str(_pick(rec, "Agent_Contact", "Agent_contact", default="") or "").strip()
    if not raw:
        return "", ""
    # phone = the longest run of digits/+/spaces at the end
    m = re.search(r"[+\d][\d\s\-()]{6,}$", raw)
    if m:
        phone = m.group(0).strip()
        name = raw[: m.start()].strip(" -–—|,")
        return name, phone
    return raw, ""


def _listing_type(rec: dict[str, Any]) -> str:
    """
    Buy vs Rent. The module no longer has a Listing Type field, so we read it from
    Status (e.g. "For Rent - Available"). Anything not mentioning rent = sale.
    """
    explicit = str(_pick(rec, "Listing_Type", "Listing_Type1", "listing_type", default="") or "").lower()
    if "rent" in explicit:
        return "rent"
    if "sale" in explicit:
        return "sale"
    status = str(_pick(rec, "Status", default="") or "").lower()
    return "rent" if "rent" in status or "let" in status else "sale"


def _normalise(rec: dict[str, Any]) -> dict[str, Any]:
    title = _pick(rec, "Name", "Title", default="Untitled listing")
    ltype = _listing_type(rec)
    agent_name, agent_phone = _split_agent(rec)
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
        "off_plan": "off plan" in str(_pick(rec, "Status", default="") or "").lower(),
        "featured": bool(_pick(rec, "Featured", default=False)),
        "description": _pick(rec, "Description", default=""),
        "images": _images(rec),
        "amenities": _amenities(rec),
        "agent_name": agent_name,
        "agent_phone": agent_phone,
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
