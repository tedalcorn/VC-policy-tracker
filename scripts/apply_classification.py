#!/usr/bin/env python3
"""Apply approved rows from suggestions.csv to the override config files.

Reads projects/2026-05-20-reclassification-pass/suggestions.csv and:
- For each row with approve == "yes", appends to article_bucket_overrides.csv
  using the suggested_buckets value (which Ted may have edited).
- If suggested_article_type is non-empty and != "article", appends to
  article_types.csv.

Idempotent: if a slug is already in the target CSV, updates that row instead
of duplicating.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUGGESTIONS = ROOT / "projects" / "2026-05-20-reclassification-pass" / "suggestions_round2.csv"
BUCKET_OVERRIDES = ROOT / "config" / "article_bucket_overrides.csv"
TYPE_OVERRIDES = ROOT / "config" / "article_types.csv"


def read_csv_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def write_csv_rows(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    if not SUGGESTIONS.exists():
        print(f"No suggestions file at {SUGGESTIONS}")
        return 1

    suggestions = read_csv_rows(SUGGESTIONS)
    approved = [r for r in suggestions if r.get("approve","yes").strip().lower() in ("yes","y","true","1")]
    skipped = len(suggestions) - len(approved)
    print(f"approved: {len(approved)}; skipped: {skipped}")

    # Merge bucket overrides
    bucket_rows = read_csv_rows(BUCKET_OVERRIDES)
    existing_buckets = {r["slug"]: r for r in bucket_rows}
    bucket_changes = 0
    for r in approved:
        slug = r["slug"]
        new = r["suggested_buckets"].strip()
        if not new:
            continue
        if slug in existing_buckets:
            existing_buckets[slug]["buckets"] = new
            existing_buckets[slug]["notes"] = "AI-suggested, user-approved 2026-05-20"
        else:
            bucket_rows.append({
                "slug": slug,
                "buckets": new,
                "notes": "AI-suggested, user-approved 2026-05-20",
            })
            existing_buckets[slug] = bucket_rows[-1]
        bucket_changes += 1
    write_csv_rows(BUCKET_OVERRIDES, ["slug","buckets","notes"], bucket_rows)
    print(f"bucket override changes: {bucket_changes}")

    # Merge article_type overrides (only non-empty, non-"article")
    type_rows = read_csv_rows(TYPE_OVERRIDES)
    existing_types = {r["slug"]: r for r in type_rows}
    type_changes = 0
    for r in approved:
        slug = r["slug"]
        t = r["suggested_article_type"].strip()
        if not t or t == "article":
            continue
        if slug in existing_types:
            existing_types[slug]["article_type"] = t
            existing_types[slug]["notes"] = "AI-suggested, user-approved 2026-05-20"
        else:
            type_rows.append({
                "slug": slug,
                "article_type": t,
                "notes": "AI-suggested, user-approved 2026-05-20",
            })
        type_changes += 1
    write_csv_rows(TYPE_OVERRIDES, ["slug","article_type","notes"], type_rows)
    print(f"article_type override changes: {type_changes}")

    print("\nNow run: python update.py --no-fetch")
    return 0


if __name__ == "__main__":
    sys.exit(main())
