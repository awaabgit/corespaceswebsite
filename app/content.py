"""
Editable page content: projects, area guides, insights, the team.

Every word on these pages lives in a YAML file under content/, not in a
template. Two reasons: Mahmoud can correct a price or a drive time without
anyone touching Python, and when Arabic is added later the templates already
have no English baked into them.

Files are read once and cached. On a serverless host each instance reads them
from its own copy of the bundle, so a deploy is what refreshes them — which is
exactly right, since the files ship with the deploy.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any

import yaml

CONTENT_DIR = Path(__file__).resolve().parent.parent / "content"

_cache: dict[str, Any] = {}


def _read_dir(kind: str) -> list[dict[str, Any]]:
    """Every .yaml in content/<kind>/, each tagged with its slug (the filename)."""
    folder = CONTENT_DIR / kind
    if not folder.is_dir():
        return []
    out = []
    for path in sorted(folder.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            # One malformed file must not take the whole site down.
            print(f"[content] skipping {path.name}: {exc}")
            continue
        if not isinstance(data, dict):
            print(f"[content] skipping {path.name}: expected a mapping")
            continue
        data.setdefault("slug", path.stem)
        out.append(data)
    return out


def all_of(kind: str) -> list[dict[str, Any]]:
    if kind not in _cache:
        _cache[kind] = _read_dir(kind)
    return _cache[kind]


def get(kind: str, slug: str) -> dict[str, Any] | None:
    for item in all_of(kind):
        if item.get("slug") == slug:
            return item
    return None


def reload() -> None:
    """Drop the cache — used by the tests and the local dev server."""
    _cache.clear()


# ------------------------------------------------------------------ projects
def projects(status: str | None = None) -> list[dict[str, Any]]:
    """All projects, or just the live / closed ones.

    A launch runs for a few weeks and then stops selling. Closed projects keep
    their page (and whatever ranking it earned) but drop out of every listing
    surface automatically, so nobody has to remember to unlink them.
    """
    items = all_of("projects")
    if status:
        items = [p for p in items if (p.get("status") or "live").lower() == status]
    return sorted(items, key=lambda p: (p.get("emirate", ""), p.get("name", "")))


def live_projects_in(area_slug: str = "", emirate: str = "") -> list[dict[str, Any]]:
    out = []
    for p in projects("live"):
        if area_slug and p.get("area_slug") == area_slug:
            out.append(p)
        elif emirate and not area_slug and \
                str(p.get("emirate", "")).lower() == emirate.lower():
            out.append(p)
    return out


# --------------------------------------------------------------------- areas
def areas() -> list[dict[str, Any]]:
    return sorted(all_of("areas"), key=lambda a: (a.get("emirate", ""), a.get("area", "")))


def areas_by_emirate() -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for a in areas():
        grouped.setdefault(a.get("emirate", "Other"), []).append(a)
    return grouped


def listings_in_area(area: dict[str, Any], rows: list[dict[str, Any]],
                     limit: int = 6) -> list[dict[str, Any]]:
    """Our own listings that sit in this area.

    Matched on whatever the agent typed into Zoho's community/location field, so
    the guide fills itself in as stock changes. `match` in the content file holds
    the spellings seen in the CRM (e.g. JVC vs Jumeirah Village Circle).
    """
    names = [str(n).lower() for n in (area.get("match") or [])]
    names.append(str(area.get("area", "")).lower())
    hits = []
    for r in rows:
        blob = " ".join(str(r.get(k, "")) for k in ("community", "location", "title")).lower()
        if any(n and n in blob for n in names):
            hits.append(r)
    return hits[:limit]


# ------------------------------------------------------------------ insights
def insights() -> list[dict[str, Any]]:
    """Newest first."""
    return sorted(all_of("insights"),
                  key=lambda a: str(a.get("published", "")), reverse=True)


def related_insights(area_slug: str = "", limit: int = 3) -> list[dict[str, Any]]:
    items = insights()
    if area_slug:
        tagged = [a for a in items if area_slug in (a.get("areas") or [])]
        if tagged:
            return tagged[:limit]
    return items[:limit]


# ---------------------------------------------------------------------- team
def team() -> list[dict[str, Any]]:
    """content/team.yaml — a list under `members`. Adding a person is one entry."""
    if "team" not in _cache:
        path = CONTENT_DIR / "team.yaml"
        data = {}
        if path.is_file():
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as exc:
                print(f"[content] team.yaml: {exc}")
        members = data.get("members") or []
        for m in members:
            m.setdefault("slug", str(m.get("name", "")).lower().replace(" ", "-"))
        _cache["team"] = members
    return _cache["team"]


def member(slug: str) -> dict[str, Any] | None:
    for m in team():
        if m.get("slug") == slug:
            return m
    return None


def fmt_date(value: Any) -> str:
    """2026-10-20 -> '20 October 2026'. Returns '' for anything unparseable."""
    text = str(value or "")[:10]
    try:
        d = _dt.date.fromisoformat(text)
    except ValueError:
        return ""
    return f"{d.day} {d.strftime('%B')} {d.year}"
