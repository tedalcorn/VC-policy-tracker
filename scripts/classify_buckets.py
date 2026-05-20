#!/usr/bin/env python3
"""AI-assisted reclassification suggestions for articles in catch-all buckets.

Reads each article that's (a) typed "article" and (b) currently sits in one
of the catch-all buckets, then asks Claude Haiku to suggest a better bucket
set using Ted's curated examples as anchors.

CRITICAL: any slug already present in config/article_bucket_overrides.csv is
SKIPPED — those are Ted's hand-curated assignments and the AI must not
suggest changes to them. They feed the prompt as exemplars instead.

Output:
  projects/2026-05-20-reclassification-pass/suggestions.csv
  columns: slug, title, date, current_buckets, suggested_buckets,
           suggested_article_type, confidence, rationale, approve

Workflow:
  1. python scripts/classify_buckets.py        # generates suggestions.csv
  2. Ted opens that CSV in his editor of choice; flips approve to "no" or
     edits suggested_buckets directly for rows that are wrong.
  3. python scripts/apply_classification.py   # merges approved rows into
                                              # config/article_bucket_overrides.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import anthropic

ROOT = Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "data" / "processed" / "articles.json"
ARTICLE_TEXT = ROOT / "data" / "processed" / "articles_text.json"
OVERRIDES = ROOT / "config" / "article_bucket_overrides.csv"
ARTICLE_TYPES = ROOT / "config" / "article_types.csv"
OUT_DIR = ROOT / "projects" / "2026-05-20-reclassification-pass"
OUT = OUT_DIR / "suggestions_round2.csv"

MODEL = "claude-haiku-4-5-20251001"
BODY_TRUNCATE = 2400

# The catch-all buckets where most over-classification lives. Articles in
# these buckets get processed first. Articles already in specific domains
# (Subway, Homelessness, Mental illness, etc.) are skipped — they're
# probably fine.
CATCH_ALL_BUCKETS = {"Crime", "Governance", "Transit", "Health & human services", "Other"}

# The full list of valid target buckets. AI must choose from these.
VALID_BUCKETS = [
    "Rikers & jails", "Criminal courts", "Policing", "Crisis response",
    "Community violence intervention", "Guns", "Drugs", "Crime data",
    "Public safety strategy", "Disorder", "Cars",
    "Mental illness", "Shoplifting", "Domestic violence", "Crime",
    "Governance", "Nonprofits", "Politics", "Housing", "Subway", "Buses", "Transit",
    "Homelessness", "Culture", "Public space", "Data", "Research",
    "Health & human services", "Youth", "Economy", "Immigration",
    "Race", "Climate", "Federal policy", "Other",
]

VALID_ARTICLE_TYPES = [
    "article", "interview", "podcast", "event", "event_transcript",
    "panel", "panel_transcript", "speech", "report", "data_product",
    "just_fix_it", "year_end_list", "anthology", "book_review",
    "press_release", "in_memoriam", "defunct", "editors_note",
    "what_we_are_reading", "correction",
]


def load_overrides() -> dict[str, list[str]]:
    if not OVERRIDES.exists():
        return {}
    out = {}
    with OVERRIDES.open(newline="") as f:
        for row in csv.DictReader(f):
            out[row["slug"]] = [b.strip() for b in row["buckets"].split(";") if b.strip()]
    return out


def load_article_types() -> dict[str, str]:
    if not ARTICLE_TYPES.exists():
        return {}
    with ARTICLE_TYPES.open(newline="") as f:
        return {row["slug"]: row["article_type"] for row in csv.DictReader(f)}


def build_exemplar_block(articles_by_slug: dict, overrides: dict, max_per_bucket: int = 3) -> str:
    """Pull a handful of slug→bucket examples per domain from the user's
    curated overrides. These ground the AI in Ted's preferences."""
    by_bucket = defaultdict(list)
    for slug, buckets in overrides.items():
        if slug not in articles_by_slug:
            continue
        title = articles_by_slug[slug].get("title", "")
        # Primary bucket = first
        by_bucket[buckets[0]].append((title, ";".join(buckets)))
    lines = ["Examples of how Ted has curated specific articles. Use these as your guide:"]
    for bucket, items in sorted(by_bucket.items()):
        for title, bucs in items[:max_per_bucket]:
            lines.append(f"  - “{title}” → {bucs}")
    return "\n".join(lines)


SYSTEM_TEMPLATE = """You're helping Ted Alcorn classify articles from Vital City (NYC civic-policy publication) into his curated domain taxonomy.

For each article you'll see, suggest the right set of domains (1-3) and, if applicable, a non-article article_type (e.g. interview, editors_note, year_end_list).

VALID DOMAINS (you must use these exact names, semicolon-separated for multi-domain):
{domains}

VALID ARTICLE TYPES (use "article" for normal articles; pick a non-article type only if the piece clearly isn't an article):
{article_types}

KEY RULES Ted has established:
- Prefer 1 domain. Use 2 only if the article truly spans them. 3+ is rare.
- "Subway" is its own domain — not the generic "Transit". Buses likewise.
- Civil litigation about a topic (e.g. gun lawsuits) → put in the topic (Guns), NOT Criminal courts.
- Criminal courts = case processing, prosecution, sentencing. Not constitutional law, not civil suits.
- "Governance" and "Culture" are over-applied by Ghost's tags. Drop them if the piece's real subject is more specific.
- "Crime" is the residual catch-all. Use it only if there's no more specific Public Safety sub-domain that fits.
- "Data" is too vague — prefer "Crime data" for crime-statistics pieces, "Research" for methodology pieces.
- Editor's notes, vital signs / state-of pieces, year-in-review, what-we're-reading, panels, anthologies — these are NOT articles.
- Civil rights / voting rights / electoral context → Politics, not Criminal courts.
- Pieces about plazas, parks, walkability, urban realm → Public space.
- Pieces about utilities/building systems → Housing (even if tagged Infrastructure).

{exemplars}

OUTPUT FORMAT — return ONLY this JSON, no other text:
{{
  "suggested_buckets": "Domain1;Domain2",
  "suggested_article_type": "article",
  "confidence": "high|medium|low",
  "rationale": "one short sentence"
}}

Confidence semantic:
- high = unambiguous; obvious match to one domain
- medium = best guess; the piece could plausibly fit elsewhere
- low = stretching; the article doesn't fit well into any of Ted's domains"""


def parse_response(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def classify_one(client, system_prompt: str, article: dict, body: str) -> dict | None:
    snippet = body[:BODY_TRUNCATE]
    msg = (
        f"Title: {article['title']}\n"
        f"Date: {article.get('published_at','')[:10]}\n"
        f"Ghost tags: {', '.join(article.get('tags',[])) or '(none)'}\n"
        f"Currently in buckets: {', '.join(article.get('buckets',[])) or '(none)'}\n"
        f"Excerpt: {article.get('excerpt') or '(none)'}\n\n"
        f"Body (truncated):\n{snippet}"
    )
    for attempt in range(3):
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=400,
                system=[{
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": msg}],
            )
            parsed = parse_response(resp.content[0].text)
            if parsed:
                return parsed
        except (anthropic.APIError, anthropic.RateLimitError) as e:
            time.sleep(2 ** attempt)
    return None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args()

    articles = json.loads(ARTICLES.read_text())
    text_by_slug = json.loads(ARTICLE_TEXT.read_text())
    overrides = load_overrides()
    type_overrides = load_article_types()
    articles_by_slug = {a["slug"]: a for a in articles}

    # Candidates: typed "article", in a catch-all bucket, NOT already overridden
    candidates = []
    for a in articles:
        if a.get("article_type") != "article":
            continue
        buckets = set(a.get("buckets", []))
        if not (buckets & CATCH_ALL_BUCKETS):
            continue
        if a["slug"] in overrides:
            continue  # USER-CURATED — sacred, don't touch
        candidates.append(a)
    candidates.sort(key=lambda a: a.get("published_at") or "", reverse=True)

    if args.limit:
        candidates = candidates[: args.limit]
    print(f"candidates: {len(candidates)}")
    print(f"  (skipped {sum(1 for s in overrides if s in articles_by_slug)} already-overridden slugs)")

    exemplar_block = build_exemplar_block(articles_by_slug, overrides)
    system_prompt = SYSTEM_TEMPLATE.format(
        domains="\n".join(f"  - {b}" for b in VALID_BUCKETS),
        article_types=", ".join(VALID_ARTICLE_TYPES),
        exemplars=exemplar_block,
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    client = anthropic.Anthropic()

    fields = ["approve", "slug", "title", "date", "current_buckets",
              "suggested_buckets", "suggested_article_type",
              "confidence", "rationale", "tags"]
    with OUT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for i, a in enumerate(candidates, 1):
            body = text_by_slug.get(a["slug"], "")
            result = classify_one(client, system_prompt, a, body)
            if not result:
                continue
            sug_buckets = result.get("suggested_buckets", "")
            cur = ";".join(a.get("buckets", []))
            # Sanity-check suggested buckets are valid
            sug_clean = [b.strip() for b in sug_buckets.split(";") if b.strip()]
            sug_clean = [b for b in sug_clean if b in VALID_BUCKETS]
            sug_buckets = ";".join(sug_clean)
            # Only output rows where the AI is suggesting a CHANGE
            cur_set = set(a.get("buckets", []))
            sug_set = set(sug_clean)
            type_change = (result.get("suggested_article_type", "article") != "article")
            if cur_set == sug_set and not type_change:
                continue
            writer.writerow({
                "approve": "yes",
                "slug": a["slug"],
                "title": a["title"],
                "date": (a.get("published_at") or "")[:10],
                "current_buckets": cur,
                "suggested_buckets": sug_buckets,
                "suggested_article_type": result.get("suggested_article_type", ""),
                "confidence": result.get("confidence", ""),
                "rationale": result.get("rationale", ""),
                "tags": ", ".join(a.get("tags", [])),
            })
            f.flush()
            if i % 25 == 0:
                print(f"  [{i}/{len(candidates)}]  {a['slug'][:50]:<50} → {sug_buckets[:40]}")

    print(f"\nWrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
