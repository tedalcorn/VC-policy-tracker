#!/usr/bin/env python3
"""Sync policy_tracking.csv with the article corpus.

Idempotent. Run after build_articles.py.

- For each article in data/processed/articles.json, ensure a row exists in
  policy_tracking.csv keyed by slug.
- Existing rows are preserved exactly. Only new slugs get appended.
- New rows get pre-filled with the agencies detected by build_articles, joined
  with semicolons. has_policy_rec starts as 'unreviewed'.
- Prints a count of new slugs added so update.py can surface "N articles need
  review" at the end.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "data" / "processed" / "articles.json"
POLICY_CSV = ROOT / "policy_tracking.csv"

FIELDS = [
    "slug",
    "published_at",
    "title",
    "url",
    "primary_author",
    "has_policy_rec",       # unreviewed | no | partial | yes | interview-only
    "rec_summary",          # one-line ask
    "agencies",             # ; separated; auto-prefilled from text scan
    "levers",               # legislation; regulation; budget; executive; internal; culture
    "geographic_scope",     # nyc | state | federal | neighborhood
    "action_status",        # none | discussed | proposed | adopted | rejected | abandoned
    "action_evidence_urls", # ; separated
    "notes",
    "last_reviewed",
]


def load_existing() -> dict[str, dict]:
    if not POLICY_CSV.exists():
        return {}
    with POLICY_CSV.open(newline="") as f:
        return {row["slug"]: row for row in csv.DictReader(f)}


def main() -> int:
    articles = json.loads(ARTICLES.read_text())
    existing = load_existing()

    new_slugs = []
    rows = []
    seen = set()

    # Iterate articles in chronological order (oldest first) so the CSV
    # reads naturally when you scroll it.
    for art in sorted(articles, key=lambda a: a.get("published_at") or ""):
        slug = art["slug"]
        seen.add(slug)
        if slug in existing:
            row = existing[slug]
            # Refresh the read-only metadata columns in case a title/author
            # got fixed upstream. Don't touch user-edited fields.
            row["published_at"] = art.get("published_at") or row.get("published_at", "")
            row["title"] = art.get("title") or row.get("title", "")
            row["url"] = art.get("url") or row.get("url", "")
            row["primary_author"] = (
                art.get("primary_author") or row.get("primary_author", "")
            )
        else:
            new_slugs.append(slug)
            agencies = "; ".join(a["name"] for a in art.get("agencies", []))
            row = {
                "slug": slug,
                "published_at": art.get("published_at", ""),
                "title": art.get("title", ""),
                "url": art.get("url", ""),
                "primary_author": art.get("primary_author", ""),
                "has_policy_rec": "unreviewed",
                "rec_summary": "",
                "agencies": agencies,
                "levers": "",
                "geographic_scope": "",
                "action_status": "",
                "action_evidence_urls": "",
                "notes": "",
                "last_reviewed": "",
            }
        # Pad any missing columns from older CSV revisions
        for col in FIELDS:
            row.setdefault(col, "")
        rows.append({k: row.get(k, "") for k in FIELDS})

    # Warn about orphans (article slugs that disappeared - rare with Ghost)
    orphans = [s for s in existing if s not in seen]

    with POLICY_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"policy_tracking.csv: {len(rows)} rows ({len(new_slugs)} new)")
    if new_slugs:
        print(f"  newest 5: " + ", ".join(new_slugs[-5:]))
    if orphans:
        print(f"  WARNING {len(orphans)} slugs in CSV not found in articles.json")
        for s in orphans[:5]:
            print(f"    {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
