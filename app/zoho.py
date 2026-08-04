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


_MODULE_CACHE: dict[str, Any] = {"name": None, "at": 0.0}


def list_modules() -> list[dict[str, Any]]:
    """Every module in the org, with API names and labels (for diagnostics)."""
    url = f"{config.ZOHO_API_HOST}/crm/v2/settings/modules"
    with httpx.Client(timeout=45) as client:
        resp = client.get(url, headers=_headers())
        resp.raise_for_status()
        return resp.json().get("modules", [])


def resolve_module() -> str:
    """
    Find the real API name of the Properties module.

    Renaming a module's LABEL in Zoho does not change its API name — a module
    shown as "Properties" can still be api_name 'Properties_New' or
    'CustomModule7'. So instead of trusting one hard-coded name we ask Zoho for
    the module list and match on label or api_name, then cache it for an hour.
    Falls back to the configured name if the lookup fails.
    """
    configured = config.ZOHO_PROPERTIES_MODULE
    now = time.time()
    if _MODULE_CACHE["name"] and now - _MODULE_CACHE["at"] < 3600:
        return _MODULE_CACHE["name"]

    try:
        modules = list_modules()
    except Exception:
        return configured

    def norm(x: str) -> str:
        return "".join(ch for ch in str(x or "").lower() if ch.isalnum())

    want = norm(configured) or "properties"
    best = None
    for m in modules:
        api = m.get("api_name", "")
        labels = [m.get("plural_label"), m.get("singular_label"), api]
        names = {norm(l) for l in labels if l}
        # exact match on the configured name wins outright
        if want in names:
            best = api
            break
        # otherwise accept a module whose label is clearly "properties"
        if best is None and "properties" in names:
            best = api

    resolved = best or configured
    _MODULE_CACHE.update({"name": resolved, "at": now})
    return resolved


def fetch_properties() -> list[dict[str, Any]]:
    """
    Pull all published listings from the custom Properties module and normalise
    them into the app's internal listing shape (same keys as mock_data).

    The module's API name is resolved automatically (see resolve_module), so a
    renamed module keeps working without a config change.
    """
    module = resolve_module()
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
    raw = _pick(rec, "Image_Upload", "Property_Photos", "Property_Photo",
                "Image_Upload_1", "Photos_Upload", "Images_Upload",
                "Record_Image", default=None)
    rid = str(rec.get("id") or "")
    if not raw or not rid:
        return []
    if isinstance(raw, str):
        return [raw] if raw.startswith("http") else []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []

    out: list[str] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        direct = (item.get("File_URL__s") or item.get("url")
                  or item.get("download_Url") or item.get("preview_Url"))
        if isinstance(direct, str) and direct.startswith("http"):
            out.append(direct)
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
    module = resolve_module()
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


_USERS_CACHE: dict[str, Any] = {"by_id": None, "at": 0.0}


def fetch_users() -> dict[str, dict[str, str]]:
    """
    Every active Zoho user, keyed by user id: {id: {name, email, phone}}.

    Agents already have a Phone on their Zoho user record (Setup → Users), so
    that's where the site gets the number to show for a listing — no second list
    to maintain, and updating a number in Zoho updates the website.

    Cached for an hour; failures return {} so a hiccup never breaks a page.
    """
    now = time.time()
    if _USERS_CACHE["by_id"] is not None and now - _USERS_CACHE["at"] < 3600:
        return _USERS_CACHE["by_id"]

    out: dict[str, dict[str, str]] = {}
    try:
        url = f"{config.ZOHO_API_HOST}/crm/v2/users"
        with httpx.Client(timeout=30) as client:
            resp = client.get(url, headers=_headers(), params={"type": "ActiveUsers"})
            resp.raise_for_status()
            for u in resp.json().get("users", []):
                uid = str(u.get("id") or "")
                if not uid:
                    continue
                full = str(u.get("full_name") or "").strip()
                if not full:
                    full = " ".join(
                        p for p in (u.get("first_name"), u.get("last_name")) if p
                    ).strip()
                out[uid] = {
                    "name": full,
                    "email": str(u.get("email") or ""),
                    # mobile is the better number to give a buyer when both exist
                    "phone": str(u.get("mobile") or u.get("phone") or "").strip(),
                }
    except Exception as exc:
        print(f"[zoho] could not load users, agent numbers fall back to config: {exc}")
        return _USERS_CACHE["by_id"] or {}

    _USERS_CACHE.update({"by_id": out, "at": now})
    return out


def _owner(rec: dict[str, Any]) -> tuple[str, str, str]:
    """
    (id, name, email) of the Zoho user who owns the record — i.e. the agent who
    posted the listing. Zoho sets this automatically on every record, which is
    why it's a reliable way to route enquiries without extra data entry.
    """
    raw = rec.get("Owner") or rec.get("owner") or {}
    if isinstance(raw, dict):
        return (str(raw.get("id") or ""),
                str(raw.get("name") or raw.get("full_name") or ""),
                str(raw.get("email") or ""))
    return "", str(raw or ""), ""


def _is_company_name(name: str) -> bool:
    """
    True when a 'person' name is really just the company name.

    The CRM's owner account is named after the company rather than the person,
    so listings it owns would otherwise show the agent as "Corespaces". Showing
    the company name where a human name belongs looks broken, so we drop it and
    let the page fall back to the main company contact instead.
    """
    def norm(s: str) -> str:
        return "".join(ch for ch in str(s or "").lower() if ch.isalnum())
    n = norm(name)
    return bool(n) and n == norm(config.COMPANY_NAME)


def _split_agent(rec: dict[str, Any]) -> tuple[str, str]:
    """
    Work out which agent a buyer should be put through to, in priority order:

      1. Agent_Name / Agent_Phone typed on the record
      2. 'Agent Contact' — one field holding both, e.g. "Sara - +971 50 123 4567"
      3. the record's Zoho Owner — name and phone read from that user's Zoho
         profile (Setup -> Users). This is the normal path and needs no data
         entry beyond filling in each agent's Phone once.
      4. the AGENTS env directory, for any agent with no phone set in Zoho
      5. nothing here; the templates fall back to the main company number

    Returns (name, phone); either may be "".
    """
    name = str(_pick(rec, "Agent_Name", "Agent_line", default="") or "")
    phone = str(_pick(rec, "Agent_Phone", "Agent_Mobile", default="") or "")

    if not (name and phone):
        raw = str(_pick(rec, "Agent_Contact", "Agent_contact", default="") or "").strip()
        if raw:
            # phone = the run of digits/+/spaces at the end
            m = re.search(r"[+\d][\d\s\-()]{6,}$", raw)
            if m:
                phone = phone or m.group(0).strip()
                name = name or raw[: m.start()].strip(" -–—|,")
            else:
                name = name or raw

    owner_id, owner_name, owner_email = _owner(rec)

    profile = fetch_users().get(owner_id, {}) if owner_id else {}
    if not name:
        name = profile.get("name") or owner_name
    if not phone:
        phone = profile.get("phone") or ""

    if not phone:
        phone = config.lookup_agent_phone(
            name, owner_name, owner_email, profile.get("email", "")
        )

    if _is_company_name(name):
        name = ""

    return name, _tidy_phone(phone)


def _tidy_phone(phone: str) -> str:
    """
    '971-563138010' -> '+971 56 313 8010'.

    Numbers get typed into Zoho every which way. Normalising here means the
    tel: and WhatsApp links work regardless of how the agent entered it.
    """
    raw = str(phone or "").strip()
    if not raw:
        return ""
    digits = "".join(c for c in raw if c.isdigit())
    if not digits:
        return raw
    if raw.startswith("00"):
        digits = digits[2:]
    # UAE mobile: 971 + 9 digits, or a local 05x number
    if digits.startswith("971") and len(digits) == 12:
        return f"+971 {digits[3:5]} {digits[5:8]} {digits[8:]}"
    if digits.startswith("0") and len(digits) == 10:
        return f"+971 {digits[1:3]} {digits[3:6]} {digits[6:]}"
    return raw if raw.startswith("+") else f"+{digits}"


# Word-boundary matching, so "Current" isn't read as rent and "completed" isn't
# read as "let". Plain substring matching got this wrong.
_RENT_WORDS = re.compile(
    r"\b(rent|rents|rental|rentals|renting|lease|leases|leased|leasing|"
    r"let|lets|letting|tolet|tenancy|tenant)\b"
)
_SALE_WORDS = re.compile(
    r"\b(sale|sales|sell|selling|sold|buy|buying|purchase|resale|freehold)\b"
)

# Fields that might carry the sale/rent decision, best first. Zoho generates API
# names from labels, so the same concept shows up under many spellings.
_TYPE_FIELDS = (
    "Listing_Type", "Listing_Type1", "Listing_Type2", "listing_type",
    "Offering_Type", "Offer_Type", "Transaction_Type", "Purpose",
    "Property_For", "For_Sale_or_Rent", "Sale_or_Rent", "Rent_or_Sale",
    "Category", "Type",
)


def _type_from_text(text: Any) -> str | None:
    """'For Rent - Available' -> 'rent'. Returns None when the text says neither."""
    s = str(text or "").lower()
    if not s:
        return None
    if _RENT_WORDS.search(s):
        return "rent"
    if _SALE_WORDS.search(s):
        return "sale"
    return None


def _listing_type(rec: dict[str, Any]) -> str:
    """
    Buy vs Rent.

    Rent listings were showing the "For sale" tag: the old version read one field,
    matched on bare substrings, and fell back to "sale" whenever it was unsure —
    so any status that didn't literally contain "rent" (e.g. "Available",
    "Ready") silently became a sale.

    Now we check every plausible field name, then Status, then the title, using
    whole-word matching. A Zoho picklist can also come back as a dict or list.
    """
    for field in _TYPE_FIELDS:
        got = _type_from_text(_flatten_picklist(_pick(rec, field, default="")))
        if got:
            return got

    for fallback in ("Status", "Availability", "Name", "Title", "Description"):
        got = _type_from_text(_flatten_picklist(_pick(rec, fallback, default="")))
        if got:
            return got

    # Genuinely no signal anywhere — sale is the safer default for a brokerage,
    # but /debug/zoho reports these so they can be fixed at the source.
    return "sale"


def _flatten_picklist(value: Any) -> str:
    """Zoho picklists arrive as a string, a {'name': ...} dict, or a list of either."""
    if isinstance(value, dict):
        return str(value.get("name") or value.get("display_value") or value.get("id") or "")
    if isinstance(value, (list, tuple)):
        return " ".join(_flatten_picklist(v) for v in value)
    return str(value or "")


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
        "area_sqft": _num(_pick(rec, "Area_Sqft", "Area_sqft", "Area")),
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
        "agent_email": _owner(rec)[2],
        # so an enquiry about this property is assigned to the agent who posted it
        "_zoho_owner_id": _owner(rec)[0],
        "_zoho_id": str(rec.get("id")),
    }


def fetch_attachment_ids(record_id: str) -> list[str]:
    """
    Return attachment IDs for a Properties record (used by the image re-host step).

    Uses resolve_module() like everything else — the configured name is only a
    hint, and a module renamed in Zoho keeps a different API name underneath.
    """
    url = f"{config.ZOHO_API_HOST}/crm/v2/{resolve_module()}/{record_id}/Attachments"
    with httpx.Client(timeout=60) as client:
        resp = client.get(url, headers=_headers())
        if resp.status_code == 204:
            return []
        resp.raise_for_status()
        return [str(a["id"]) for a in resp.json().get("data", [])]


def download_attachment(record_id: str, attachment_id: str) -> bytes:
    url = (
        f"{config.ZOHO_API_HOST}/crm/v2/{resolve_module()}"
        f"/{record_id}/Attachments/{attachment_id}"
    )
    with httpx.Client(timeout=120) as client:
        resp = client.get(url, headers=_headers())
        resp.raise_for_status()
        return resp.content


def create_lead(name: str, email: str, phone: str, message: str,
                listing_title: str = "", owner_id: str = "") -> dict[str, Any]:
    """
    Create a Lead in Zoho from a website inquiry.

    When the enquiry is about a specific property, `owner_id` is the Zoho user who
    posted that listing — we assign the Lead to them so it lands in the right
    agent's queue instead of sitting unassigned. If Zoho rejects the assignment
    (user deactivated, id stale), we retry unassigned rather than lose the lead.
    """
    url = f"{config.ZOHO_API_HOST}/crm/v2/Leads"
    record: dict[str, Any] = {
        "Last_Name": name.strip() or "Website Lead",
        "Email": email,
        "Phone": phone,
        "Lead_Source": "Website",
        "Description": f"[Re: {listing_title}]\n\n{message}" if listing_title else message,
    }
    if owner_id:
        record["Owner"] = {"id": owner_id}

    with httpx.Client(timeout=30) as client:
        resp = client.post(url, headers=_headers(), json={"data": [record]})
        if owner_id and resp.status_code >= 400:
            record.pop("Owner", None)
            resp = client.post(url, headers=_headers(), json={"data": [record]})
        resp.raise_for_status()
        return resp.json()


def _num(v: Any) -> float:
    """
    Parse a number the way people actually type it: 2,650,000 / AED 2,650,000 /
    695.56 / "1 340". Strips anything that isn't a digit, dot or minus so a comma
    in the field never silently becomes 0.
    """
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    cleaned = re.sub(r"[^0-9.\-]", "", str(v))
    if cleaned in ("", ".", "-", "-."):
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _slugify(text: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in text)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


def diagnose() -> dict[str, Any]:
    """
    Plain-English health check for the Zoho link. Visit /debug/zoho to see it.
    Shows which module was found, how many records came back, how many are
    published, and the exact field names on the first record.
    """
    out: dict[str, Any] = {"configured_module": config.ZOHO_PROPERTIES_MODULE}
    try:
        mods = list_modules()
        out["modules_visible"] = [
            {"api_name": m.get("api_name"), "label": m.get("plural_label")}
            for m in mods if m.get("api_name")
        ][:60]
    except Exception as e:
        out["module_list_error"] = f"{type(e).__name__}: {e}"

    try:
        module = resolve_module()
        out["resolved_module"] = module
        url = f"{config.ZOHO_API_HOST}/crm/v2/{module}"
        with httpx.Client(timeout=45) as client:
            resp = client.get(url, headers=_headers(), params={"per_page": 5})
        out["status_code"] = resp.status_code
        if resp.status_code == 204:
            out["records_returned"] = 0
            out["hint"] = "Module found but it has no records."
        else:
            data = resp.json().get("data", [])
            out["records_returned"] = len(data)
            if data:
                first = data[0]
                out["first_record_fields"] = sorted(first.keys())
                out["first_record_published"] = _is_published(first)
                out["published_count"] = sum(1 for r in data if _is_published(r))
                if not out["first_record_published"]:
                    out["hint"] = ("Records exist but none are published. Tick "
                                   "'Publish to Web' and make sure Status is not "
                                   "Sold / Off Market.")

                # Why did each record come out as Buy or Rent? Shows the raw
                # values behind the decision so a mis-tagged listing is
                # traceable to the exact Zoho field.
                out["sale_rent_check"] = [
                    {
                        "title": _pick(r, "Name", "Title", default="?"),
                        "decided": _listing_type(r),
                        "status_field": _flatten_picklist(_pick(r, "Status", default="")),
                        "type_fields": {
                            f: _flatten_picklist(r[f])
                            for f in _TYPE_FIELDS if f in r and r[f] not in (None, "", [])
                        },
                        "owner": _owner(r)[1],
                        "agent_shown": _split_agent(r),
                    }
                    for r in data[:5]
                ]
                out["zoho_users"] = [
                    {"name": u["name"], "email": u["email"],
                     "phone_on_file": u["phone"] or "— MISSING, add it in Setup → Users"}
                    for u in fetch_users().values()
                ]
                out["agent_directory_loaded"] = sorted(config.agent_directory().keys())
            else:
                out["hint"] = "Module found but returned no records."
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out
