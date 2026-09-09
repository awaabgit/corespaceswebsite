"""
Team KPI tracker — the /kpi page.

Staff log their daily activity numbers; managers see the whole team as well as
their own. Everything is rendered server-side.

That last point is a deliberate departure from the React version this replaces,
and it is worth saying why. The rest of this site reads Supabase with the
SERVICE ROLE key from the server and keeps RLS on with no public policies (see
supabase/schema.sql). The React original did the opposite: anon key, queries
issued from the browser. Running it that way here would have meant granting
public read on kpi_users — a table that holds every staff password in plain
text — so anyone who found the page could read the lot out of the network tab.
Doing the queries server-side keeps that table unreachable from the browser and
leaves the project's existing "RLS on, service role only" arrangement intact.
The browser is only ever sent numbers that have already been rendered.

Tables (create these in Supabase; they are not in supabase/schema.sql):
  kpi_users   (name text, passcode text, role text)   role: 'member' | 'manager'
  kpi_entries (member text, entry_date date, + one int column per KPI key,
               unique on (member, entry_date))
"""
from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any

from . import config

# ---------------------------------------------------------------- the targets
# From Mahmoud's brief. Weekly target is the daily figure across a 5-day week.
KPIS = [
    {"key": "outbound",      "label": "Total outbound calls",       "short": "Outbound",      "daily": 100, "monthly": 2200},
    {"key": "connected",     "label": "Connected calls",            "short": "Connected",     "daily": 30,  "monthly": 660},
    {"key": "conversations", "label": "Meaningful conversations",   "short": "Conversations", "daily": 15,  "monthly": 330},
    {"key": "qualified",     "label": "Qualified prospects",        "short": "Qualified",     "daily": 5,   "monthly": 110},
    {"key": "meetings",      "label": "Meetings / viewings booked", "short": "Meetings",      "daily": 2,   "monthly": 44},
]
WORK_DAYS_WEEK = 5
SESSION_COOKIE = "cs_kpi"
SESSION_HOURS = 12


# ------------------------------------------------------------- configuration
# The KPI tables normally live in the same Supabase project as the listings, so
# these default to the main credentials. The overrides exist because the tracker
# was originally built against a separate project — if that is where the tables
# actually are, point these at it rather than moving the data.
def _kpi_url() -> str:
    return (os.getenv("KPI_SUPABASE_URL") or config.SUPABASE_URL or "").strip()


def _kpi_key() -> str:
    return (os.getenv("KPI_SUPABASE_KEY") or config.SUPABASE_KEY or "").strip()


def _session_secret() -> bytes:
    """
    Key that signs the login cookie.

    Falls back to deriving one from the service-role key, which is already a
    server-only secret and — importantly on serverless — is identical across
    instances. A randomly generated per-process key would look fine locally and
    then log people out at random in production, whenever a request happened to
    land on a different instance than the one that issued the cookie.
    """
    explicit = (os.getenv("KPI_SECRET") or "").strip()
    if explicit:
        return explicit.encode("utf-8")
    key = _kpi_key()
    if key:
        return hmac.new(key.encode("utf-8"), b"cs-kpi-session-v1", hashlib.sha256).digest()
    return b""


def enabled() -> bool:
    """False when the page has nothing to talk to — it then says so plainly."""
    return bool(_kpi_url() and _kpi_key() and _session_secret())


_client = None


def _get_client():
    global _client
    if _client is None:
        from supabase import create_client  # lazy, exactly as supabase_client.py does
        _client = create_client(_kpi_url(), _kpi_key())
    return _client


# -------------------------------------------------------------- date helpers
def today_iso() -> str:
    return _dt.date.today().isoformat()


def _parse(s: str) -> _dt.date:
    try:
        return _dt.date.fromisoformat((s or "")[:10])
    except (TypeError, ValueError):
        return _dt.date.today()


def monday_of(s: str) -> str:
    d = _parse(s)
    return (d - _dt.timedelta(days=d.weekday())).isoformat()


def week_dates(anchor: str) -> list[str]:
    start = _parse(monday_of(anchor))
    return [(start + _dt.timedelta(days=i)).isoformat() for i in range(7)]


def shift_week(anchor: str, direction: int) -> str:
    return (_parse(monday_of(anchor)) + _dt.timedelta(weeks=direction)).isoformat()


def month_key(s: str) -> str:
    return (s or "")[:7]


def month_bounds(anchor: str) -> tuple[str, str]:
    d = _parse(anchor)
    first = d.replace(day=1)
    nxt = (first + _dt.timedelta(days=32)).replace(day=1)
    return first.isoformat(), (nxt - _dt.timedelta(days=1)).isoformat()


def fmt_day(s: str) -> str:
    d = _parse(s)
    # Built by hand rather than with %-d, which isn't portable off glibc.
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b')}"


# --------------------------------------------------------------------- login
# The passwords in kpi_users are short and plain text, so an unthrottled login
# form is a free brute-force oracle. Same shape as the inquiry limiter in
# main.py: count recent failures per IP and stop answering for a while.
_LOGIN_FAILS: dict[str, list[float]] = {}
_LOGIN_MAX = 8
_LOGIN_WINDOW = 300.0


def login_blocked(ip: str) -> bool:
    now = time.monotonic()
    recent = [t for t in _LOGIN_FAILS.get(ip, []) if now - t < _LOGIN_WINDOW]
    if recent:
        _LOGIN_FAILS[ip] = recent
    else:
        _LOGIN_FAILS.pop(ip, None)
    return len(recent) >= _LOGIN_MAX


def note_login_failure(ip: str) -> None:
    if len(_LOGIN_FAILS) > 5000:      # crude cap so this can't grow forever
        _LOGIN_FAILS.clear()
    _LOGIN_FAILS.setdefault(ip, []).append(time.monotonic())


def authenticate(name: str, password: str) -> dict[str, str] | None:
    """Returns {'name','role'} on success, None on any failure."""
    name = (name or "").strip()
    password = (password or "").strip()
    if not name or not password:
        return None
    try:
        res = (_get_client().table("kpi_users")
               .select("name,role,passcode").ilike("name", name).limit(1).execute())
    except Exception as exc:
        print(f"[kpi] user lookup failed: {exc}")
        raise
    rows = res.data or []
    if not rows:
        # Still burn a comparison so a missing name and a wrong password don't
        # take visibly different amounts of time.
        secrets.compare_digest(password, "no-such-user")
        return None
    row = rows[0]
    if not secrets.compare_digest(str(row.get("passcode") or ""), password):
        return None
    role = str(row.get("role") or "member").strip().lower()
    return {"name": str(row.get("name") or name), "role": "manager" if role == "manager" else "member"}


# ------------------------------------------------------------------ sessions
def make_token(name: str, role: str) -> str:
    payload = json.dumps({"n": name, "r": role, "x": int(time.time()) + SESSION_HOURS * 3600},
                         separators=(",", ":")).encode("utf-8")
    body = base64.urlsafe_b64encode(payload).rstrip(b"=")
    sig = base64.urlsafe_b64encode(
        hmac.new(_session_secret(), body, hashlib.sha256).digest()).rstrip(b"=")
    return (body + b"." + sig).decode("ascii")


def read_token(token: str | None) -> dict[str, str] | None:
    secret = _session_secret()
    if not token or not secret:
        return None
    try:
        body, _, sig = token.encode("ascii").partition(b".")
        expected = base64.urlsafe_b64encode(
            hmac.new(secret, body, hashlib.sha256).digest()).rstrip(b"=")
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(base64.urlsafe_b64decode(body + b"=" * (-len(body) % 4)))
        if int(data.get("x", 0)) < time.time():
            return None
        role = "manager" if data.get("r") == "manager" else "member"
        return {"name": str(data["n"]), "role": role}
    except Exception:
        return None


# ------------------------------------------------------------------ the data
def list_members() -> list[str]:
    res = _get_client().table("kpi_users").select("name,role").eq("role", "member").execute()
    return sorted(str(r.get("name") or "") for r in (res.data or []) if r.get("name"))


def fetch_entries(start: str, end: str, member: str | None = None) -> list[dict[str, Any]]:
    q = (_get_client().table("kpi_entries").select("*")
         .gte("entry_date", start).lte("entry_date", end))
    if member:
        q = q.eq("member", member)
    return q.execute().data or []


def save_entry(member: str, entry_date: str, values: dict[str, Any]) -> None:
    row: dict[str, Any] = {"member": member, "entry_date": entry_date}
    for k in KPIS:
        row[k["key"]] = _clean_int(values.get(k["key"]))
    _get_client().table("kpi_entries").upsert(row, on_conflict="member,entry_date").execute()


def _clean_int(v: Any) -> int:
    try:
        n = int(float(str(v).strip() or 0))
    except (TypeError, ValueError):
        return 0
    return max(0, n)


# ----------------------------------------------------------------- reporting
def totals(entries: list[dict], member: str, dates: set[str]) -> dict[str, int]:
    out = {k["key"]: 0 for k in KPIS}
    for e in entries:
        if e.get("member") != member or e.get("entry_date") not in dates:
            continue
        for k in KPIS:
            out[k["key"]] += _clean_int(e.get(k["key"]))
    return out


def bar_color(pct: float) -> str:
    if pct >= 100:
        return "#1E7A44"
    if pct >= 60:
        return "#C2A24E"
    if pct >= 30:
        return "#D98A2B"
    return "#B03A2E"


def progress_rows(sums: dict[str, int], period: str) -> list[dict[str, Any]]:
    """One row per KPI: value, target, capped bar width, colour."""
    rows = []
    for k in KPIS:
        target = k["daily"] * WORK_DAYS_WEEK if period == "week" else k["monthly"]
        value = sums.get(k["key"], 0)
        pct = (value / target * 100) if target else 0.0
        rows.append({"label": k["label"], "value": value, "target": target,
                     "pct": min(100.0, pct), "raw_pct": pct, "color": bar_color(pct)})
    return rows


def member_report(entries: list[dict], member: str, anchor: str) -> dict[str, Any]:
    wdates = week_dates(anchor)
    m_start, m_end = month_bounds(anchor)
    mdates = set()
    d, last = _parse(m_start), _parse(m_end)
    while d <= last:
        mdates.add(d.isoformat())
        d += _dt.timedelta(days=1)

    by_date = {e["entry_date"]: e for e in entries
               if e.get("member") == member and e.get("entry_date")}

    log = []
    for iso in wdates:
        row = by_date.get(iso) or {}
        cells = [_clean_int(row.get(k["key"])) for k in KPIS]
        log.append({"label": fmt_day(iso), "cells": cells,
                    "has": any(cells), "is_today": iso == today_iso()})

    today_row = by_date.get(today_iso()) or {}
    return {
        "name": member,
        "week": progress_rows(totals(entries, member, set(wdates)), "week"),
        "month": progress_rows(totals(entries, member, mdates), "month"),
        "month_label": month_key(anchor),
        "log": log,
        "today_values": {k["key"]: today_row.get(k["key"], "") for k in KPIS},
        "has_today": bool(today_row),
    }


def team_cards(entries: list[dict], members: list[str], anchor: str) -> list[dict[str, Any]]:
    wdates = set(week_dates(anchor))
    cards = []
    for name in members:
        rows = progress_rows(totals(entries, name, wdates), "week")
        avg = round(sum(r["pct"] for r in rows) / len(rows)) if rows else 0
        cards.append({"name": name, "avg": avg, "rows": rows, "color": bar_color(avg)})
    return cards
