"""
The ONE place the website asks for data. Routes to the right source based on
config.mode(), so routes in main.py never care whether data is mock, Supabase,
or live Zoho. Swap modes by setting env vars — no code changes.
"""
from __future__ import annotations

import time
from typing import Any

from . import config
from .mock_data import MOCK_LISTINGS


def get_listings(
    *, listing_type: str | None = None, search: str | None = None,
    beds: int | None = None, max_price: int | None = None,
    baths: int | None = None, min_sqft: int | None = None,
    min_price: int | None = None, status: str | None = None,
) -> list[dict[str, Any]]:
    rows = _all_listings()

    if listing_type in ("sale", "rent"):
        rows = [r for r in rows if r.get("type") == listing_type]

    if beds:
        rows = [r for r in rows if int(r.get("beds", 0)) >= beds]

    if baths:
        rows = [r for r in rows if int(r.get("baths", 0) or 0) >= baths]

    if min_sqft:
        rows = [r for r in rows if float(r.get("area_sqft", 0) or 0) >= min_sqft]

    if min_price:
        rows = [r for r in rows if r.get("price") and r["price"] >= min_price]

    if max_price:
        rows = [r for r in rows if r.get("price") and r["price"] <= max_price]

    if status:
        st = status.lower()
        if st == "ready":
            rows = [r for r in rows if "ready" in str(r.get("status", "")).lower()]
        elif st == "offplan":
            rows = [r for r in rows if "off plan" in str(r.get("status", "")).lower()]
        elif st == "available":
            rows = [r for r in rows
                    if "available" in str(r.get("status", "")).lower()]

    if search:
        q = search.lower().strip()
        rows = [
            r
            for r in rows
            if q in r.get("title", "").lower()
            or q in r.get("location", "").lower()
            or q in r.get("community", "").lower()
        ]

    # featured first, then leave source order
    rows.sort(key=lambda r: (not r.get("featured", False)))
    return rows


def get_featured(limit: int = 3) -> list[dict[str, Any]]:
    featured = [r for r in _all_listings() if r.get("featured")]
    return (featured or _all_listings())[:limit]


def get_listing(slug: str) -> dict[str, Any] | None:
    for r in _all_listings():
        if r.get("slug") == slug:
            return r
    return None


def create_inquiry(
    name: str, email: str, phone: str, message: str, listing: dict[str, Any] | None = None
) -> None:
    """
    Send an inquiry wherever we can. Best effort: push to Zoho as a Lead, and/or
    log to Supabase. In mock mode it just prints so you can see it working.
    """
    title = listing.get("title", "") if listing else ""
    slug = listing.get("slug", "") if listing else ""
    # the agent who posted this listing — the lead gets assigned to them
    owner_id = listing.get("_zoho_owner_id", "") if listing else ""

    if config.zoho_enabled():
        from . import zoho
        zoho.create_lead(name, email, phone, message,
                         listing_title=title, owner_id=owner_id)

    if config.supabase_enabled():
        from . import supabase_client
        supabase_client.log_lead(name, email, phone, message, listing_slug=slug)

    if config.mode() == "mock":
        print(
            f"[INQUIRY • mock mode] {name} <{email}> {phone} | re: {title or 'general'}\n"
            f"  {message}"
        )


# --------------------------------------------------------------------- cache
# Without this, every single page view hit the live source — the home page, each
# listing page and the sitemap each triggered a full paginated Zoho fetch. That
# is slow and burns through Zoho's API rate limit.
#
# One fetch now serves every visitor for CACHE_TTL seconds. Just as important:
# if the live source fails we keep serving the LAST GOOD data rather than
# swapping in sample listings, so a brief Zoho outage can never put fake
# properties and fake phone numbers in front of a real customer.
_CACHE_TTL = float(config.LISTINGS_CACHE_TTL)
_cache: dict[str, Any] = {"rows": None, "at": 0.0}


def invalidate_cache() -> None:
    """Force the next read to go back to the live source."""
    _cache["rows"] = None
    _cache["at"] = 0.0


def _fallback(reason: str) -> list[dict[str, Any]]:
    """
    What to show when the live source gives us nothing and we have no cached
    copy. Sample listings are fine for a demo but dangerous in production — they
    carry invented agents and phone numbers — so they're opt-in.
    """
    if _cache["rows"]:
        print(f"[data] {reason}; serving last known-good listings")
        return _cache["rows"]
    if config.SHOW_SAMPLES_ON_FAILURE:
        print(f"[data] {reason}; falling back to sample listings")
        return MOCK_LISTINGS
    print(f"[data] {reason}; showing no listings (set SHOW_SAMPLES_ON_FAILURE=1 to use samples)")
    return []


def _all_listings() -> list[dict[str, Any]]:
    m = config.mode()
    if m == "mock":
        return MOCK_LISTINGS

    now = time.monotonic()
    if _cache["rows"] is not None and (now - _cache["at"]) < _CACHE_TTL:
        return _cache["rows"]

    try:
        if m == "supabase":
            from . import supabase_client
            rows = supabase_client.get_listings()
        else:  # zoho-direct
            from . import zoho
            rows = zoho.fetch_properties()
    except Exception as exc:  # never let a live-source hiccup break the public site
        return _fallback(f"live source '{m}' failed ({exc})")

    if not rows:
        return _fallback(f"live source '{m}' returned no published listings")

    _cache["rows"] = rows
    _cache["at"] = now
    return rows
