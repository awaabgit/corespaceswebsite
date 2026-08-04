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
COMPANY_PHONE = _get("COMPANY_PHONE", "+971 56 313 8010")
COMPANY_EMAIL = _get("COMPANY_EMAIL", "najam@corespaces.info")
COMPANY_ADDRESS = _get("COMPANY_ADDRESS", "Business Bay, Dubai, UAE")

# --- Agent directory (fallback only) ------------------------------------------
# Each property shows the agent handling it: Zoho stamps every record with an
# Owner, and the site reads that user's Phone straight from their Zoho profile
# (Setup -> Users -> the agent -> Phone / Mobile). Fill that in once per agent
# and there is nothing to configure here.
#
# This variable is only a safety net for an agent whose Zoho profile has no
# phone number on it:
#
#   AGENTS="Francis Ahovi:+971501112222;cophy8080@gmail.com:+971503334444"
#
# Keys can be a name OR an email, whichever matches the Zoho user. A record's
# own Agent_Name / Agent_Phone fields still win over everything.
AGENTS_RAW = _get("AGENTS", "")


def _norm_key(s: str) -> str:
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


def agent_directory() -> dict[str, str]:
    """{normalised name-or-email: phone}. Bad entries are skipped, never fatal."""
    out: dict[str, str] = {}
    for entry in AGENTS_RAW.split(";"):
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        key, _, phone = entry.rpartition(":")
        key, phone = key.strip(), phone.strip()
        if key and phone:
            out[_norm_key(key)] = phone
    return out


def lookup_agent_phone(*candidates: str) -> str:
    """First candidate (name or email) that matches a directory entry."""
    directory = agent_directory()
    if not directory:
        return ""
    for c in candidates:
        if not c:
            continue
        hit = directory.get(_norm_key(c))
        if hit:
            return hit
        # also try the local part of an email: najam@corespaces.ae -> najam
        if "@" in str(c):
            hit = directory.get(_norm_key(str(c).split("@")[0]))
            if hit:
                return hit
    return ""

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

# --- Behaviour ---------------------------------------------------------------
# How long (seconds) a fetched set of listings is reused before going back to the
# live source. Keeps the site fast and well inside Zoho's API rate limits.
def _get_float(key: str, default: float) -> float:
    """A typo in an env var shouldn't take the site down — fall back instead."""
    try:
        return float(_get(key) or default)
    except ValueError:
        return default


LISTINGS_CACHE_TTL = _get_float("LISTINGS_CACHE_TTL", 90.0)

# If the live source fails on a cold start, should we show the built-in SAMPLE
# listings? They contain invented properties, agents and phone numbers, so this
# is off by default — a real visitor should never be given a fake number to ring.
# Set to 1 only for demos.
SHOW_SAMPLES_ON_FAILURE = _get("SHOW_SAMPLES_ON_FAILURE", "").lower() in ("1", "true", "yes")

# /debug/zoho exposes your CRM module and field names. Set this and the endpoint
# requires ?key=<value>; leave blank to disable the endpoint entirely.
DEBUG_KEY = _get("DEBUG_KEY")


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
