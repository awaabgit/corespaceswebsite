"""
Titles, meta descriptions and structured data.

Two rules behind this module:

1. JSON-LD is built as Python dicts and serialised with json.dumps, never
   written by hand in a template. The hand-written version broke on every
   listing whose description contained a line break — a raw newline is illegal
   inside a JSON string, so all 30 property pages shipped structured data that
   no search engine could parse. Building it here makes that failure mode
   impossible: json.dumps escapes whatever it is given.

2. Titles and descriptions are generated from the listing's own fields, so a
   new property gets a useful title without anyone writing one.
"""
from __future__ import annotations

import html
import json
import re
from typing import Any

from . import config

# Agents type building names in caps. "AMNA TOWER" reads as shouting in a search
# result, but blanket .title() would wreck the acronyms, so those are preserved.
ACRONYMS = {
    "DAMAC", "JVC", "JLT", "DSO", "JBR", "MBR", "UAE", "DIFC", "IMPZ", "DIP",
    "MAG", "DEC", "SZR", "ROI", "LLC", "OST", "II", "III", "IV",
}
_SMALL = {"by", "the", "of", "at", "on", "in", "and", "for", "to", "a"}


def tidy_name(text: str) -> str:
    """'AMNA TOWER' -> 'Amna Tower'; 'DAMAC PARK CANAL' -> 'DAMAC Park Canal'."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return ""
    words = []
    for i, raw in enumerate(text.split(" ")):
        bare = raw.strip("(),-").upper()
        if bare in ACRONYMS:
            words.append(raw.upper() if raw.isupper() else raw)
            continue
        # Leave deliberate mixed case alone (e.g. "iCube", "AlMas")
        if raw != raw.upper() and raw != raw.lower() and not raw[:1].isupper():
            words.append(raw)
            continue
        low = raw.lower()
        if i and low in _SMALL:
            words.append(low)
        else:
            words.append(low[:1].upper() + low[1:])
    return " ".join(words)


def short_price(value: Any, listing_type: str = "sale", currency: str = "AED") -> str:
    """3500000 -> 'AED 3.5M'; a rent -> 'AED 95K/yr'. '' when there's no price."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    suffix = "/yr" if listing_type == "rent" else ""
    if n >= 1_000_000:
        m = n / 1_000_000
        body = f"{m:.1f}".rstrip("0").rstrip(".") + "M"
    elif n >= 1_000:
        body = f"{n / 1_000:.0f}K"
    else:
        body = f"{int(n):,}"
    return f"{currency} {body}{suffix}"


def beds_label(beds: Any) -> str:
    try:
        n = int(beds or 0)
    except (TypeError, ValueError):
        n = 0
    return "Studio" if n <= 0 else f"{n} Bed"


def _kind(listing: dict[str, Any]) -> str:
    """Townhouse / Villa / Apartment, guessed from the title then the type field."""
    blob = " ".join(str(listing.get(k, "")) for k in ("title", "property_type", "type")).lower()
    for word, label in (("townhouse", "Townhouse"), ("villa", "Villa"),
                        ("penthouse", "Penthouse"), ("plot", "Plot"),
                        ("office", "Office"), ("studio", "Apartment")):
        if word in blob:
            return label
    return "Apartment"


def _area(listing: dict[str, Any]) -> str:
    return tidy_name(listing.get("community") or listing.get("location") or "")


# Words that mark a CRM title as a sales headline ("Exceptional 3 Bedroom
# Apartment for Sale in …") rather than the building's name.
_HEADLINE = re.compile(
    r"\b(\d+\s*-?\s*(bed|bedroom|br|bhk)s?|bedrooms?|studio|apartment|villa|"
    r"townhouse|penthouse|duplex|offices?|for (sale|rent)|luxury|exceptional|"
    r"stunning|views?|brand new|furnished|maid)\b", re.I)


def _building(listing: dict[str, Any]) -> str:
    """The building's name — or '' when the CRM title is a sales headline, in
    which case the title falls back to the community name instead."""
    title = str(listing.get("title") or "").strip()
    if not title or _HEADLINE.search(title) or len(title.split()) > 6:
        return ""
    return tidy_name(title)


def _what(listing: dict[str, Any]) -> str:
    """'2 Bed Apartment', 'Studio Apartment', '4 Bed Villa', 'Office'."""
    kind = _kind(listing)
    if kind in ("Office", "Plot"):
        return kind
    label = beds_label(listing.get("beds"))
    if label == "Studio" and kind != "Apartment":
        return kind          # a 0-bed villa is a data gap, not a studio villa
    return f"{label} {kind}"


def _where(listing: dict[str, Any]) -> str:
    """'Amna Tower, Business Bay' — building then area, skipping the area when
    it just repeats the building name."""
    building, area = _building(listing), _area(listing)
    parts = [building] if building else []
    if area and area.lower() != building.lower():
        parts.append(area)
    return ", ".join(parts) or area or config.CITY


def clamp(text: str, limit: int) -> str:
    """Trim to a limit on a word boundary rather than mid-word."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,.–—-")
    return cut


# ----------------------------------------------------------------- titles
def listing_title(listing: dict[str, Any]) -> str:
    """'2 Bed Apartment for Sale in Amna Tower, Business Bay | AED 3.5M'"""
    deal = "Rent" if listing.get("type") == "rent" else "Sale"
    where = _where(listing)
    head = f"{_what(listing)} for {deal} in {where}"
    price = short_price(listing.get("price"), listing.get("type", "sale"),
                        listing.get("currency", "AED"))
    full = f"{head} | {price}" if price else head
    if len(full) <= 65:
        return full
    head = clamp(head, 65 - (len(price) + 3) if price else 65)
    return f"{head} | {price}" if price else head


def listing_h1(listing: dict[str, Any]) -> str:
    """Same shape as the title, without the price — the visible heading."""
    deal = "Rent" if listing.get("type") == "rent" else "Sale"
    where = _where(listing)
    return f"{_what(listing)} for {deal} in {where}"


def listing_description(listing: dict[str, Any]) -> str:
    what = _what(listing)
    bits = [what if what.startswith("Studio") else what.lower()]
    try:
        sqft = float(listing.get("area_sqft") or 0)
        if sqft > 0:
            bits.append(f"{int(sqft):,} sqft")
    except (TypeError, ValueError):
        pass
    where = _area(listing) or _building(listing)
    if where:
        bits.append(f"in {where}")
    price = short_price(listing.get("price"), listing.get("type", "sale"),
                        listing.get("currency", "AED"))
    lead = ", ".join(bits[:2]) + (" " + " ".join(bits[2:]) if bits[2:] else "")
    lead = lead[:1].upper() + lead[1:]
    tail = f". {price}." if price else "."
    return clamp(f"{lead}{tail} View photos, floor area and price, and arrange a viewing "
                 f"with {config.BRAND_NAME}.", 155)


def listing_alt(listing: dict[str, Any], n: int = 1) -> str:
    """'2 bed apartment in Amna Tower, Business Bay - photo 1'"""
    what = _what(listing)
    what = what if what.startswith("Studio") else what.lower()
    return f"{what} in {_where(listing)} - photo {n}"


# ------------------------------------------------------------- structured data
def _clean(value: Any) -> str:
    """Flatten to one line. json.dumps would escape a newline legally, but \\n in
    a description helps nobody reading a search result."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


def render(data: dict[str, Any] | list[dict[str, Any]]) -> str:
    """A JSON-LD payload safe to drop straight into a <script> tag.

    `</script>` inside a string would otherwise end the tag early and break the
    page, so the forward slash is escaped — valid JSON, inert HTML.
    """
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return text.replace("</", "<\\/")


def organisation(base_url: str) -> dict[str, Any]:
    node: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "RealEstateAgent",
        "@id": f"{base_url}/#organisation",
        "name": config.BRAND_NAME,
        "legalName": config.LEGAL_NAME,
        "url": base_url or "",
        "logo": f"{base_url}/static/core-spaces-logo.jpg",
        "image": f"{base_url}/static/core-spaces-logo.jpg",
        "telephone": config.BUSINESS_PHONE,
        "email": config.BUSINESS_EMAIL,
        "address": {
            "@type": "PostalAddress",
            "streetAddress": config.STREET_ADDRESS,
            "addressLocality": config.CITY,
            "addressCountry": config.COUNTRY,
        },
        "areaServed": [
            {"@type": "City", "name": "Dubai"},
            {"@type": "City", "name": "Sharjah"},
        ],
    }
    if config.ORN:
        node["identifier"] = {"@type": "PropertyValue", "name": "ORN", "value": config.ORN}
    socials = config.social_urls()
    if socials:
        node["sameAs"] = socials
    return node


def breadcrumbs(base_url: str, trail: list[tuple[str, str]]) -> dict[str, Any]:
    """trail = [(name, path), ...] from Home to the current page."""
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i, "name": name, "item": f"{base_url}{path}"}
            for i, (name, path) in enumerate(trail, start=1)
        ],
    }


def listing_node(listing: dict[str, Any], base_url: str, url: str) -> dict[str, Any]:
    price = listing.get("price")
    available = "https://schema.org/InStock"
    if any(w in str(listing.get("status", "")).lower()
           for w in ("sold", "let agreed", "under offer", "off market")):
        available = "https://schema.org/SoldOut"

    node: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "RealEstateListing",
        "url": url,
        "name": _clean(listing.get("title")),
        "description": _clean(listing.get("description"))[:600],
        "datePosted": str(listing.get("created_at") or "")[:10] or None,
        "address": {
            "@type": "PostalAddress",
            "addressLocality": _clean(listing.get("community") or listing.get("location")) or config.CITY,
            "addressRegion": _clean(listing.get("location")) or config.CITY,
            "addressCountry": config.COUNTRY,
        },
        "provider": {"@id": f"{base_url}/#organisation"},
    }
    if listing.get("images"):
        node["image"] = [str(i) for i in listing["images"][:6]]
    try:
        if float(price or 0) > 0:
            node["offers"] = {
                "@type": "Offer",
                "price": float(price),
                "priceCurrency": listing.get("currency") or "AED",
                "availability": available,
                "url": url,
            }
    except (TypeError, ValueError):
        pass

    try:
        sqft = float(listing.get("area_sqft") or 0)
        if sqft > 0:
            node["floorSize"] = {"@type": "QuantitativeValue", "value": sqft,
                                 "unitCode": "FTK"}
    except (TypeError, ValueError):
        pass
    try:
        beds = int(listing.get("beds") or 0)
        if beds > 0:
            node["numberOfRooms"] = beds
    except (TypeError, ValueError):
        pass
    try:
        baths = int(listing.get("baths") or 0)
        if baths > 0:
            node["numberOfBathroomsTotal"] = baths
    except (TypeError, ValueError):
        pass

    return {k: v for k, v in node.items() if v not in (None, "", [], {})}


def faq_node(faqs: list[dict[str, str]]) -> dict[str, Any] | None:
    items = [f for f in (faqs or []) if f.get("q") and f.get("a")]
    if not items:
        return None
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": _clean(f["q"]),
             "acceptedAnswer": {"@type": "Answer", "text": _clean(f["a"])}}
            for f in items
        ],
    }


def article_node(article: dict[str, Any], base_url: str, url: str) -> dict[str, Any]:
    author = article.get("author") or {}
    node: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": _clean(article.get("h1") or article.get("title"))[:110],
        "description": _clean(article.get("meta_description")),
        "url": url,
        "mainEntityOfPage": url,
        "datePublished": str(article.get("published") or "")[:10] or None,
        "dateModified": str(article.get("updated") or article.get("published") or "")[:10] or None,
        "publisher": {"@id": f"{base_url}/#organisation"},
    }
    if author.get("name"):
        node["author"] = {
            "@type": "Person",
            "name": author["name"],
            "jobTitle": author.get("role") or None,
            "url": f"{base_url}{author['url']}" if author.get("url") else None,
            "worksFor": {"@id": f"{base_url}/#organisation"},
        }
        node["author"] = {k: v for k, v in node["author"].items() if v}
    if article.get("og_image"):
        node["image"] = f"{base_url}{article['og_image']}"
    return {k: v for k, v in node.items() if v not in (None, "", [], {})}


def person_node(member: dict[str, Any], base_url: str) -> dict[str, Any]:
    node: dict[str, Any] = {
        "@type": "Person",
        "@id": f"{base_url}/team#{member.get('slug', '')}",
        "name": member.get("name"),
        "jobTitle": member.get("role"),
        "worksFor": {"@id": f"{base_url}/#organisation"},
    }
    if member.get("languages"):
        node["knowsLanguage"] = list(member["languages"])
    if member.get("photo"):
        node["image"] = f"{base_url}{member['photo']}"
    if member.get("brn"):
        node["identifier"] = {"@type": "PropertyValue", "name": "BRN",
                              "value": str(member["brn"])}
    return {k: v for k, v in node.items() if v not in (None, "", [], {})}
