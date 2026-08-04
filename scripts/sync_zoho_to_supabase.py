#!/usr/bin/env python3
"""
SYNC: Zoho Properties  ->  Supabase (listings cache + re-hosted images)

Run this on a schedule (cron / systemd timer). The website only ever reads
Supabase, so it stays fast and never hits Zoho's API rate limits.

Flow per listing:
  1. Pull published records from the Zoho custom Properties module.
  2. For each, download its photo attachments from Zoho (server-side, authed).
  3. Re-upload those photos to the public Supabase bucket.
  4. Upsert the listing row (with the new public image URLs) into Supabase.

Usage:
  python scripts/sync_zoho_to_supabase.py

Requires (in .env): all ZOHO_* and SUPABASE_* vars, plus `pip install supabase`.

Suggested cron (every 15 min):
  */15 * * * * cd /srv/realty-zoho-site && /srv/realty-zoho-site/.venv/bin/python scripts/sync_zoho_to_supabase.py >> /var/log/realty-sync.log 2>&1
"""
import sys
from pathlib import Path

# allow `from app import ...` when run from the project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, zoho, supabase_client  # noqa: E402


def run() -> None:
    if not config.zoho_enabled():
        print("ABORT: Zoho creds missing. Set ZOHO_* in .env.")
        sys.exit(1)
    if not config.supabase_enabled():
        print("ABORT: Supabase creds missing. Set SUPABASE_* in .env.")
        sys.exit(1)

    print("Fetching properties from Zoho...")
    listings = zoho.fetch_properties()
    print(f"  {len(listings)} published listing(s) found.")

    rows = []
    for listing in listings:
        zoho_id = listing.get("_zoho_id")
        owner_id = listing.get("_zoho_owner_id", "")
        # Keys starting with "_" are internal to the app and have no column in
        # Supabase — sending them would make the upsert fail on an unknown column.
        listing = {k: v for k, v in listing.items() if not k.startswith("_")}
        listing["zoho_owner_id"] = owner_id
        image_urls = []

        # Only fetch/re-host attachments if the record didn't already carry URLs.
        if not listing.get("images") and zoho_id:
            try:
                att_ids = zoho.fetch_attachment_ids(zoho_id)
                for i, att_id in enumerate(att_ids):
                    raw = zoho.download_attachment(zoho_id, att_id)
                    path = f"{listing['slug']}/{i}.jpg"
                    url = supabase_client.upload_image(path, raw, "image/jpeg")
                    image_urls.append(url)
                print(f"  · {listing['slug']}: re-hosted {len(image_urls)} photo(s)")
            except Exception as exc:
                print(f"  ! {listing['slug']}: image sync failed ({exc})")
            listing["images"] = image_urls

        rows.append(listing)

    count = supabase_client.upsert_listings(rows)
    print(f"Done. Upserted {count} listing(s) into Supabase.")


if __name__ == "__main__":
    run()
