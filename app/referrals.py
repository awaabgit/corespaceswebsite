"""
Personal links: corespaces.info/<name> for each member of the team.

Someone taps corespaces.info/kassim in Kassim's Instagram bio. We remember that
in a cookie for 30 days and show them the normal home page. If they later send
an enquiry — from the contact page or from any listing — the lead reaches Zoho
labelled with Kassim's link and assigned to Kassim, so whoever brought the
client in gets the client.

Who the lead is assigned to, in order:
  1. the team member's own Zoho user, if exactly one Zoho user matches them
  2. the manager (Mahmoud), if the team member isn't in Zoho
  3. nobody — Zoho's default — but the label still says whose link it was

Set REFERRAL_ROUTING=manager to send every link's leads to the manager instead
(still labelled), e.g. while the team's Zoho accounts are being set up.
"""
from __future__ import annotations

import os

from fastapi import Request

# slug -> the name shown on the lead. Adding someone is one line here + a deploy.
# Slugs must not clash with a real page (about, contact, listings, kpi, ...).
TEAM: dict[str, str] = {
    "francis": "Francis",
    "kassim": "Kassim",
    "emmanuel": "Emmanuel",
    "mohammed": "Mohammed",
    "mohamed": "Mohamed",
    "mahmoud": "Mahmoud",
    "najam": "Najam",
}
MANAGER = "mahmoud"

COOKIE = "cs_ref"
COOKIE_DAYS = 30


def name_for(slug: str) -> str:
    return TEAM.get((slug or "").strip().lower(), "")


def from_request(request: Request) -> str:
    """The referring slug from the visitor's cookie, or '' — never trusted blind:
    anything not on the team list is ignored."""
    slug = (request.cookies.get(COOKIE) or "").strip().lower()
    return slug if slug in TEAM else ""


# ------------------------------------------------------------ Zoho matching
def _email_overrides() -> dict[str, str]:
    """
    REFERRAL_ZOHO_EMAILS="kassim:kassim@corespaces.info;mohamed:mo@corespaces.info"

    Only needed when a first name can't pick out one Zoho user on its own — two
    people sharing a first name, or a Zoho profile under a different name.
    """
    out: dict[str, str] = {}
    for entry in (os.getenv("REFERRAL_ZOHO_EMAILS") or "").split(";"):
        slug, _, email = entry.partition(":")
        if slug.strip() and email.strip():
            out[slug.strip().lower()] = email.strip().lower()
    return out


def _zoho_user_id(slug: str, users: dict[str, dict[str, str]]) -> str:
    """The Zoho user id for a team member, or '' unless exactly one user matches.
    A guess that assigns a lead to the wrong person is worse than no guess."""
    email = _email_overrides().get(slug)
    if email:
        hits = [uid for uid, u in users.items() if u.get("email", "").lower() == email]
    else:
        first = name_for(slug).lower()
        # Exact first word, so "Mohamed" and "Mohammed" stay two different people.
        hits = [uid for uid, u in users.items()
                if (u.get("name", "").split() or [""])[0].lower() == first]
    return hits[0] if len(hits) == 1 else ""


def route(slug: str) -> tuple[str, str]:
    """(zoho owner id or '', label for the top of the lead) for a referral."""
    name = name_for(slug)
    label = f"Came from {name}'s link — corespaces.info/{slug}"
    manager = name_for(MANAGER)

    try:
        from . import zoho
        users = zoho.fetch_users()
    except Exception as exc:
        print(f"[referral] Zoho users unavailable ({exc}); lead stays unassigned")
        users = {}

    to_manager = (os.getenv("REFERRAL_ROUTING") or "").strip().lower() == "manager"
    if not to_manager:
        uid = _zoho_user_id(slug, users)
        if uid:
            return uid, label

    mid = _zoho_user_id(MANAGER, users)
    if mid:
        why = "" if (to_manager or slug == MANAGER) else f" ({name} isn't set up in Zoho yet)"
        return mid, f"{label}\nAssigned to {manager}{why}."
    who = manager if slug == MANAGER else f"{name} nor {manager}"
    return "", f"{label}\nNot assigned — {'' if slug == MANAGER else 'neither '}{who} was found in Zoho."
