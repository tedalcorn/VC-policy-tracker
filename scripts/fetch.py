#!/usr/bin/env python3
"""Fetch Vital City posts from the Ghost content API.

Writes data/raw/vital_city_posts_with_tags.json (full dump).
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw" / "vital_city_posts_with_tags.json"

API_KEY = "dd8e178e9ddfc883537e71dd07"
POSTS_URL = "https://vital-city.ghost.io/ghost/api/content/posts/"


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    posts: list[dict] = []
    params = {"key": API_KEY, "limit": 100, "page": 1, "include": "authors,tags"}
    while True:
        url = POSTS_URL + "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.load(resp)
        posts.extend(data["posts"])
        nxt = data["meta"]["pagination"]["next"]
        print(f"page {params['page']}: {len(data['posts'])} posts (total {len(posts)})")
        if not nxt:
            break
        params["page"] = nxt
    OUT.write_text(json.dumps(posts))
    print(f"wrote {len(posts)} posts to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
