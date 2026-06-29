"""
Central configuration. Everything is read from environment variables (.env).

The whole app is built to run in THREE modes with zero code changes — it picks
the mode automatically based on which env vars are present:

  1. MOCK   (default, no creds)      -> serves sample listings from mock_data.py
  2. SUPABASE (Supabase creds set)   -> serves cached listings synced from Zoho
  3. ZOHO-DIRECT (Zoho creds set,    -> hits Zoho live (use only for testing;
     no Supabase)                        prefer SUPABASE mode in production)

In production you want: a cron runs scripts/sync_zoho_to_supabase.py, which
fills Supabase, and the website reads Supabase (fast, no rate limits).
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _get(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


# --- Company / branding (FINISH phase: drop in the investor's real values) ---
COMPANY_NAME = _get("COMPANY_NAME", "CORE Spaces")
COMPANY_TAGLINE = _get("COMPANY_TAGLINE", "Dubai property, brokered properly.")
COMPANY_PHONE = _get("COMPANY_PHONE", "+971 4 000 0000")
COMPANY_EMAIL = _get("COMPANY_EMAIL", "hello@corespaces.ae")
COMPANY_ADDRESS = _get("COMPANY_ADDRESS", "Business Bay, Dubai, UAE")

# --- Supabase (cache + image bucket + leads log) ---
SUPABASE_URL = _get("SUPABASE_URL")
SUPABASE_KEY = _get("SUPABASE_KEY")  # service role key (server-side only)
SUPABASE_BUCKET = _get("SUPABASE_BUCKET", "listing-photos")

# --- Zoho CRM ---
ZOHO_CLIENT_ID = _get("ZOHO_CLIENT_ID")
ZOHO_CLIENT_SECRET = _get("ZOHO_CLIENT_SECRET")
ZOHO_REFRESH_TOKEN = _get("ZOHO_REFRESH_TOKEN")
# Data centre domain: .com / .eu / .in / .com.au / .sa  (UAE accounts are usually .com)
ZOHO_ACCOUNTS_HOST = _get("ZOHO_ACCOUNTS_HOST", "https://accounts.zoho.com")
ZOHO_API_HOST = _get("ZOHO_API_HOST", "https://www.zohoapis.com")
# The API name of your custom listings module (you create this in Zoho — see zoho/properties_module_schema.md)
ZOHO_PROPERTIES_MODULE = _get("ZOHO_PROPERTIES_MODULE", "Properties")


def supabase_enabled() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)


def zoho_enabled() -> bool:
    return bool(ZOHO_CLIENT_ID and ZOHO_CLIENT_SECRET and ZOHO_REFRESH_TOKEN)


def mode() -> str:
    if supabase_enabled():
        return "supabase"
    if zoho_enabled():
        return "zoho-direct"
    return "mock"
