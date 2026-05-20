#!/usr/bin/env python3
"""Assemble the dashboard's data bundle into site/data/.

Reads:
- data/processed/articles.json
- data/processed/build_summary.json
- data/processed/articles_text.json
- data/processed/vital_city_author_master.csv  (if present)
- policy_tracking.csv

Writes everything into site/data/ so the dashboard can fetch over plain
HTTP without crossing project root.
"""

from __future__ import annotations

import csv
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
POLICY_CSV = ROOT / "policy_tracking.csv"
POLICY_SCORES_CSV = PROCESSED / "policy_scores.csv"
SITE_DATA = ROOT / "site" / "data"


def load_policy() -> dict[str, dict]:
    if not POLICY_CSV.exists():
        return {}
    with POLICY_CSV.open(newline="") as f:
        return {row["slug"]: row for row in csv.DictReader(f)}


def load_policy_scores() -> dict[str, dict]:
    if not POLICY_SCORES_CSV.exists():
        return {}
    with POLICY_SCORES_CSV.open(newline="") as f:
        scores = {row["slug"]: row for row in csv.DictReader(f)}
    # Merge in supporting excerpts if extracted
    excerpts_path = PROCESSED / "policy_excerpts.csv"
    if excerpts_path.exists():
        with excerpts_path.open(newline="") as f:
            for r in csv.DictReader(f):
                if r["slug"] in scores:
                    scores[r["slug"]]["supporting_excerpt"] = r["supporting_excerpt"]
    return scores


def load_author_master() -> list[dict]:
    path = PROCESSED / "vital_city_author_master.csv"
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def main() -> int:
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    articles = json.loads((PROCESSED / "articles.json").read_text())
    summary = json.loads((PROCESSED / "build_summary.json").read_text())
    policy = load_policy()
    scores = load_policy_scores()
    authors = load_author_master()

    # Articles file: lightweight - no plaintext.
    (SITE_DATA / "articles.json").write_text(
        json.dumps(articles, ensure_ascii=False, separators=(",", ":"))
    )
    # Plaintext is loaded on demand by the search feature.
    shutil.copyfile(
        PROCESSED / "articles_text.json", SITE_DATA / "articles_text.json"
    )
    # Policy tracking as a slug-keyed map for O(1) joins on the client.
    (SITE_DATA / "policy_tracking.json").write_text(
        json.dumps(policy, ensure_ascii=False, separators=(",", ":"))
    )
    # AI policy scores (if scorer has been run).
    (SITE_DATA / "policy_scores.json").write_text(
        json.dumps(scores, ensure_ascii=False, separators=(",", ":"))
    )
    # Author research master file (profession, employer, etc.)
    (SITE_DATA / "authors.json").write_text(
        json.dumps(authors, ensure_ascii=False, separators=(",", ":"))
    )
    # Summary stats for dashboard header + topic chart.
    (SITE_DATA / "build_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
    )

    print(f"site/data: {len(articles)} articles, "
          f"{len(policy)} policy rows, {len(scores)} ai scores, "
          f"{len(authors)} authors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
