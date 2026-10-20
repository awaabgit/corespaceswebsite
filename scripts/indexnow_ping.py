#!/usr/bin/env python3
"""
Tell Bing (and the other IndexNow engines) about every URL in the live sitemap.

Run after a production deploy — the GitHub workflow in
.github/workflows/indexnow.yml does this automatically when Vercel reports a
successful production deployment. Safe to run by hand any time:

    python3 scripts/indexnow_ping.py                 # corespaces.info
    python3 scripts/indexnow_ping.py --dry-run       # list what would be sent

The key is public by design: the site serves it at /<key>.txt so the search
engine can check the ping really came from the site's owner.
"""
import json
import os
import re
import sys
import urllib.request

HOST = os.getenv("INDEXNOW_HOST", "corespaces.info")
KEY = os.getenv("INDEXNOW_KEY", "8f3c1e7a52d94b6e9a0c4d2f7b1e6a35")
ENDPOINT = "https://api.indexnow.org/indexnow"


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "corespaces-indexnow"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def main() -> int:
    base = f"https://{HOST}"
    # Refuse to ping if the key file isn't live yet — the engine would reject it.
    try:
        served = fetch(f"{base}/{KEY}.txt").strip()
    except Exception as exc:
        print(f"key file not reachable at {base}/{KEY}.txt ({exc}); not pinging")
        return 1
    if served != KEY:
        print("key file content doesn't match the key; not pinging")
        return 1

    urls = re.findall(r"<loc>([^<]+)</loc>", fetch(f"{base}/sitemap.xml"))
    urls = [u.replace("&amp;", "&") for u in urls][:10000]
    print(f"{len(urls)} URLs in the sitemap")
    if "--dry-run" in sys.argv:
        for u in urls:
            print("  ", u)
        return 0

    body = json.dumps({"host": HOST, "key": KEY,
                       "keyLocation": f"{base}/{KEY}.txt", "urlList": urls}).encode()
    req = urllib.request.Request(ENDPOINT, data=body, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"IndexNow answered {r.status}")   # 200 or 202 = accepted
            return 0
    except urllib.error.HTTPError as exc:
        print(f"IndexNow refused: {exc.code} {exc.reason}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
