"""
The ONE place the website asks for data. Routes to the right source based on
config.mode(), so routes in main.py never care whether data is mock, Supabase,
or live Zoho. Swap modes by setting env vars — no code changes.
"""
from __future__ import annotations

from typing import Any

from . import config
from .mock_data import MOCK_LISTINGS


def get_listings(
    *, listing_type: str | None = None, search: str | None = None,
    beds: int | None = None, max_price: int | None = None,
) -> list[dict[str, Any]]:
    rows = _all_listings()

    if listing_type in ("sale", "rent"):
        rows = [r for r in rows if r.get("type") == listing_type]

    if beds:
        rows = [r for r in rows if int(r.get("beds", 0)) >= beds]

    if max_price:
        rows = [r for r in rows if r.get("price") and r["price"] <= max_price]

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

    if config.zoho_enabled():
        from . import zoho
        zoho.create_lead(name, email, phone, message, listing_title=title)

    if config.supabase_enabled():
        from . import supabase_client
        supabase_client.log_lead(name, email, phone, message, listing_slug=slug)

    if config.mode() == "mock":
        print(
            f"[INQUIRY • mock mode] {name} <{email}> {phone} | re: {title or 'general'}\n"
            f"  {message}"
        )


def _all_listings() -> list[dict[str, Any]]:
    m = config.mode()
    try:
        if m == "supabase":
            from . import supabase_client
            return supabase_client.get_listings()
        if m == "zoho-direct":
            from . import zoho
            rows = zoho.fetch_properties()
            # If Zoho is reachable but nothing is published yet, show samples so
            # the site is never blank during a demo. Real published rows win.
            return rows if rows else MOCK_LISTINGS
    except Exception as exc:  # never let a live-source hiccup break the public site
        print(f"[data] live source '{m}' failed, falling back to samples: {exc}")
        return MOCK_LISTINGS
    return MOCK_LISTINGS
