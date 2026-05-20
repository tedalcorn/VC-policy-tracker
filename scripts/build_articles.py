#!/usr/bin/env python3
"""Process raw Ghost posts into the dashboard's article records.

Inputs:
- data/raw/vital_city_posts_with_tags.json (output of scripts/fetch.py)
- config/tag_bucket_map.csv
- config/agency_patterns.csv

Outputs:
- data/processed/articles.json
- data/processed/articles_text.json   (separate so the main file stays small)
- data/processed/build_summary.json

Each article record contains:
  slug, url, title, published_at, year, primary_author, authors, all_tags,
  buckets, excerpt, reading_time, word_count, agencies_mentioned, feature_image

articles_text.json keys by slug → plaintext body (loaded on-demand by the
dashboard's search feature).
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "vital_city_posts_with_tags.json"
PROCESSED = ROOT / "data" / "processed"
BUCKET_MAP = ROOT / "config" / "tag_bucket_map.csv"
AGENCY_PATTERNS = ROOT / "config" / "agency_patterns.csv"
BYLINE_ALIASES = ROOT / "config" / "byline_aliases.csv"
ARTICLE_TYPES = ROOT / "config" / "article_types.csv"

# Surname particles that should be folded into the last name for sorting.
# "Brandon del Pozo" -> "del Pozo", "Vishaan Chakrabarti" -> "Chakrabarti".
SURNAME_PARTICLES = {
    "de", "del", "della", "der", "den", "di", "da", "du",
    "van", "von", "vom", "zu", "le", "la", "ten", "ter",
    "bin", "ibn", "al", "el",
}


class _TextExtractor(HTMLParser):
    """Strip HTML to plaintext while preserving paragraph breaks."""

    BLOCK_TAGS = {
        "p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6",
        "blockquote", "tr", "pre",
    }
    SKIP_TAGS = {"script", "style"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip_depth:
            return
        self.parts.append(data)

    def text(self) -> str:
        joined = "".join(self.parts)
        joined = re.sub(r"\s*\n\s*", "\n", joined)
        joined = re.sub(r"\n{3,}", "\n\n", joined)
        return joined.strip()


def html_to_text(html: str) -> str:
    if not html:
        return ""
    parser = _TextExtractor()
    parser.feed(html)
    return parser.text()


def load_bucket_map() -> dict[str, str]:
    with BUCKET_MAP.open(newline="") as f:
        reader = csv.DictReader(f)
        return {row["tag"]: row["bucket"] for row in reader}


def load_agency_patterns() -> list[tuple[str, str, re.Pattern]]:
    out = []
    with AGENCY_PATTERNS.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pat = re.compile(row["patterns"], flags=re.IGNORECASE)
            out.append((row["display_name"], row["level"], pat))
    return out


def find_agencies(text: str, patterns) -> list[dict]:
    """Return a list of dicts {name, level, hits} for each agency mentioned."""
    if not text:
        return []
    hits = []
    for name, level, pat in patterns:
        matches = pat.findall(text)
        if matches:
            hits.append({"name": name, "level": level, "hits": len(matches)})
    hits.sort(key=lambda x: -x["hits"])
    return hits


def load_byline_aliases() -> dict[str, str]:
    if not BYLINE_ALIASES.exists():
        return {}
    with BYLINE_ALIASES.open(newline="") as f:
        return {row["original"]: row["replacement"] for row in csv.DictReader(f)}


def load_article_type_overrides() -> dict[str, str]:
    if not ARTICLE_TYPES.exists():
        return {}
    with ARTICLE_TYPES.open(newline="") as f:
        return {row["slug"]: row["article_type"] for row in csv.DictReader(f)}


def derive_article_type(tags: list[str], slug: str, overrides: dict[str, str]) -> str:
    """Pick an article_type from explicit overrides, then tag-based heuristics."""
    if slug in overrides:
        return overrides[slug]
    tagset = set(tags)
    if "Press Releases" in tagset:
        return "press_release"
    if "Just Fix It" in tagset:
        return "just_fix_it"
    if "Events" in tagset:
        return "event"
    if "Podcast" in tagset:
        return "podcast"
    if "Data Stories" in tagset and "data" in tagset:
        return "data_product"
    if slug.startswith("vital-signs-"):
        return "data_product"
    if "interview" in tagset:
        return "interview"
    if "Comings and Goings" in tagset:
        return "interview"
    if "Reality Check" in tagset:
        return "data_product"
    if "Book Review" in tagset:
        return "book_review"
    if "In Memoriam" in tagset:
        return "in_memoriam"
    if "Corrections" in tagset:
        return "correction"
    return "article"


def compute_last_name(name: str) -> str:
    """Best-effort surname extraction for alphabetical sorting."""
    if not name:
        return ""
    if name == "No byline":
        # Sort No byline at the very end of the alphabet.
        return "zzzz"
    parts = name.replace(",", " ").split()
    if not parts:
        return name.lower()
    # If second-to-last token is a particle, include it.
    if len(parts) >= 3 and parts[-2].lower() in SURNAME_PARTICLES:
        return (parts[-2] + " " + parts[-1]).lower()
    return parts[-1].lower()


def normalize_buckets(tag_names: list[str], bucket_map: dict[str, str]) -> list[str]:
    seen = []
    for t in tag_names:
        bucket = bucket_map.get(t)
        if bucket and bucket not in seen:
            seen.append(bucket)
    if not seen:
        seen.append("Other")
    return seen


def main() -> None:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    posts = json.loads(RAW.read_text())
    bucket_map = load_bucket_map()
    agency_patterns = load_agency_patterns()
    byline_aliases = load_byline_aliases()
    type_overrides = load_article_type_overrides()

    articles = []
    article_text = {}
    bucket_counter = Counter()
    bucket_year = defaultdict(lambda: Counter())
    agency_counter = Counter()
    unmapped_tags = Counter()
    article_type_counter = Counter()

    for post in posts:
        slug = post["slug"]
        html = post.get("html") or ""
        plaintext = html_to_text(html)
        word_count = len(re.findall(r"\b\w+\b", plaintext))

        public_tags = [
            t["name"]
            for t in (post.get("tags") or [])
            if t.get("visibility") == "public"
        ]
        for t in public_tags:
            if t not in bucket_map:
                unmapped_tags[t] += 1

        buckets = normalize_buckets(public_tags, bucket_map)
        for b in buckets:
            bucket_counter[b] += 1

        published_at = (post.get("published_at") or "")[:19]
        year = int(published_at[:4]) if published_at[:4].isdigit() else None
        if year:
            for b in buckets:
                bucket_year[b][year] += 1

        agencies = find_agencies(plaintext, agency_patterns)
        for a in agencies:
            agency_counter[a["name"]] += 1

        raw_authors = [a["name"] for a in (post.get("authors") or [])]
        authors = [byline_aliases.get(n, n) for n in raw_authors]
        raw_primary = (
            post.get("primary_author", {}).get("name")
            if post.get("primary_author")
            else (raw_authors[0] if raw_authors else "")
        )
        primary_author = byline_aliases.get(raw_primary, raw_primary)

        article_type = derive_article_type(public_tags, slug, type_overrides)
        article_type_counter[article_type] += 1

        articles.append({
            "slug": slug,
            "url": post.get("url", ""),
            "title": post.get("title", ""),
            "published_at": published_at,
            "year": year,
            "primary_author": primary_author,
            "primary_author_last": compute_last_name(primary_author),
            "authors": authors,
            "article_type": article_type,
            "tags": public_tags,
            "buckets": buckets,
            "excerpt": (post.get("custom_excerpt") or post.get("excerpt") or "").strip(),
            "reading_time": post.get("reading_time", 0),
            "word_count": word_count,
            "agencies": agencies,
            "feature_image": post.get("feature_image", ""),
        })
        article_text[slug] = plaintext

    articles.sort(key=lambda a: (a["published_at"] or ""), reverse=True)

    (PROCESSED / "articles.json").write_text(
        json.dumps(articles, ensure_ascii=False, separators=(",", ":"))
    )
    (PROCESSED / "articles_text.json").write_text(
        json.dumps(article_text, ensure_ascii=False, separators=(",", ":"))
    )

    summary = {
        "total_articles": len(articles),
        "date_range": [
            min(a["published_at"] for a in articles if a["published_at"]),
            max(a["published_at"] for a in articles if a["published_at"]),
        ],
        "bucket_totals": dict(bucket_counter.most_common()),
        "bucket_by_year": {
            b: dict(sorted(years.items())) for b, years in bucket_year.items()
        },
        "agency_totals": dict(agency_counter.most_common()),
        "article_type_totals": dict(article_type_counter.most_common()),
        "unmapped_tags": dict(unmapped_tags.most_common()),
    }
    (PROCESSED / "build_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2)
    )

    print(f"articles: {summary['total_articles']}")
    print(f"date range: {summary['date_range'][0]} -> {summary['date_range'][1]}")
    print(f"unmapped tags: {len(summary['unmapped_tags'])}")
    print("bucket totals:")
    for b, n in summary["bucket_totals"].items():
        print(f"  {n:4d}  {b}")
    print(f"agencies detected (top 20):")
    for name, n in list(summary["agency_totals"].items())[:20]:
        print(f"  {n:4d}  {name}")
    print(f"article types:")
    for t, n in summary["article_type_totals"].items():
        print(f"  {n:4d}  {t}")


if __name__ == "__main__":
    sys.exit(main())
