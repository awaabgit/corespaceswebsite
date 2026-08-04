"""
Supabase access — the website's fast read path and the leads log.

Lazy: the `supabase` package is only imported when creds exist, so the app
imports and runs in mock mode even if supabase isn't installed.

Tables (see supabase/schema.sql):
  - listings : the cached, web-ready listings synced from Zoho
  - leads    : website inquiries (also pushed to Zoho; this is a local backup)
Storage:
  - bucket `listing-photos` : public, holds re-hosted listing images
"""
from __future__ import annotations

from typing import Any

from . import config

_client = None


def _get_client():
    global _client
    if _client is None:
        from supabase import create_client  # lazy import
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
    return _client


# Statuses that mean "don't show this on the website". Everything else is shown.
#
# This used to be an exact `status == "available"` match, which was wrong: the
# sync writes Zoho's own wording through, so real rows arrive as "ready",
# "off plan", "for rent - available" and so on. An exact match would have hidden
# almost every listing the moment we switched to Supabase mode. Excluding the
# handful of dead states is both correct and safe against new status wording.
_HIDDEN_STATUS_WORDS = ("sold", "off market", "off-market", "let agreed",
                        "under offer", "withdrawn", "archived")


def _is_visible(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or "").lower()
    return not any(word in status for word in _HIDDEN_STATUS_WORDS)


def get_listings() -> list[dict[str, Any]]:
    res = (
        _get_client()
        .table("listings")
        .select("*")
        .order("featured", desc=True)
        .order("created_at", desc=True)
        .execute()
    )
    return [r for r in (res.data or []) if _is_visible(r)]


def get_listing(slug: str) -> dict[str, Any] | None:
    res = _get_client().table("listings").select("*").eq("slug", slug).limit(1).execute()
    return (res.data or [None])[0]


def upsert_listings(rows: list[dict[str, Any]]) -> int:
    """Used by the sync script. Upserts on `slug`."""
    if not rows:
        return 0
    _get_client().table("listings").upsert(rows, on_conflict="slug").execute()
    return len(rows)


def log_lead(name: str, email: str, phone: str, message: str, listing_slug: str = "") -> None:
    _get_client().table("leads").insert(
        {
            "name": name,
            "email": email,
            "phone": phone,
            "message": message,
            "listing_slug": listing_slug,
        }
    ).execute()


def upload_image(path: str, data: bytes, content_type: str = "image/jpeg") -> str:
    """Upload bytes to the public bucket and return the public URL."""
    client = _get_client()
    bucket = config.SUPABASE_BUCKET
    client.storage.from_(bucket).upload(
        path,
        data,
        {"content-type": content_type, "upsert": "true"},
    )
    return client.storage.from_(bucket).get_public_url(path)
