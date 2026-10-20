"""
Turn the plain text in content/*.yaml into HTML.

A deliberately tiny subset of Markdown — paragraphs, "- " bullet lists,
[links](url) and **bold** — so the content files stay readable and anyone can
edit them, and so there is no Markdown dependency to keep patched. Everything
is HTML-escaped first: a stray "<" in a content file can never become markup.
"""
from __future__ import annotations

import html
import re

from markupsafe import Markup

_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")


def _inline(text: str) -> str:
    out = html.escape(text, quote=True)

    def link(m: re.Match) -> str:
        label, url = m.group(1), m.group(2)
        if url.startswith(("http://", "https://")):
            return (f'<a href="{url}" target="_blank" rel="noopener">{label}</a>')
        return f'<a href="{url}">{label}</a>'

    out = _LINK.sub(link, out)
    return _BOLD.sub(r"<strong>\1</strong>", out)


def render(text: str | None) -> Markup:
    if not text:
        return Markup("")
    blocks = re.split(r"\n\s*\n", str(text).strip())
    parts: list[str] = []
    for block in blocks:
        lines = [ln.rstrip() for ln in block.strip().splitlines()]
        if lines and lines[0].lstrip().startswith("- "):
            items: list[str] = []
            for ln in lines:
                if ln.lstrip().startswith("- "):
                    items.append(ln.lstrip()[2:].strip())
                elif items:
                    items[-1] += " " + ln.strip()   # wrapped continuation line
            parts.append("<ul>" + "".join(f"<li>{_inline(i)}</li>" for i in items) + "</ul>")
        else:
            parts.append(f"<p>{_inline(' '.join(ln.strip() for ln in lines))}</p>")
    return Markup("\n".join(parts))


def plain(text: str | None) -> str:
    """The same text with the link/bold markup stripped — for counting words
    and for JSON-LD, where markup would be noise."""
    t = _LINK.sub(r"\1", str(text or ""))
    t = _BOLD.sub(r"\1", t)
    t = re.sub(r"^\s*-\s+", "", t, flags=re.M)
    return re.sub(r"\s+", " ", t).strip()
