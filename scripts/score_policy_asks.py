#!/usr/bin/env python3
"""Score every article on the strength of its policy recommendation.

Scope:
  Only article_type == "article" (skips interviews, panels, podcasts, reports,
  press releases, etc. — those have their own logic and don't follow the same
  "does this make a specific ask" question).

Method:
  One Claude Haiku call per article. Pass the title + excerpt + first ~3000
  chars of body. Ask for a 0-5 score, a one-line rationale, and (if score >= 3)
  the policy ask + agency/official target.

Output:
  data/processed/policy_scores.csv  (slug, score, has_policy_rec, policy_ask,
                                     target, rationale, model, scored_at)

  Resumable: skips slugs already in the CSV.

Run:
  python scripts/score_policy_asks.py             # full run, all eligible
  python scripts/score_policy_asks.py --limit 30  # sample first
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

import anthropic

ROOT = Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "data" / "processed" / "articles.json"
ARTICLE_TEXT = ROOT / "data" / "processed" / "articles_text.json"
OUT = ROOT / "data" / "processed" / "policy_scores.csv"

MODEL = "claude-haiku-4-5-20251001"
BODY_TRUNCATE = 3000  # chars; ~750 tokens

SYSTEM = """You evaluate articles from Vital City, a New York City civic-policy publication, for one question:

How clearly does this article make a SPECIFIC POLICY RECOMMENDATION directed at a government actor (agency, official, branch, or body)?

Use this 0-5 scale:

5 — Explicit, named recommendation directed at a specific named actor.
    Example: "The NYPD should reinstate its gang database with the following four reforms..."

4 — Specific recommendation, but the audience is unnamed or vague.
    Example: "The city should adopt congestion pricing on these corridors..."  (no agency named)

3 — Clear policy preference but no specific action requested.
    Example: "Cash bail should be reconsidered" — direction is clear, but no concrete what/who.

2 — Mostly analytical with an implicit normative claim. The author has a view but doesn't pivot to a recommendation.

1 — Pure analysis, history, or explainer. No policy stance taken.

0 — Article doesn't fit the framework at all (memorial, profile, personal essay, art criticism).

Return ONLY this JSON, no other text:
{
  "score": 0-5,
  "has_policy_rec": "yes" | "partial" | "no",
  "policy_ask": "one-sentence summary, or null if score < 3",
  "target": "the named agency/official/body/branch being asked, or null if not named",
  "rationale": "one short sentence explaining the score"
}

Map scores: 4-5 -> "yes"; 3 -> "partial"; 0-2 -> "no"."""


def load_existing() -> dict[str, dict]:
    if not OUT.exists():
        return {}
    with OUT.open(newline="") as f:
        return {row["slug"]: row for row in csv.DictReader(f)}


def parse_response(text: str) -> dict | None:
    """Strip any preamble/codefence and parse JSON."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def score_article(client: anthropic.Anthropic, article: dict, body: str) -> dict | None:
    snippet = body[:BODY_TRUNCATE]
    user_msg = (
        f"Title: {article['title']}\n\n"
        f"Excerpt: {article.get('excerpt') or '(none)'}\n\n"
        f"Body (truncated):\n{snippet}"
    )
    last_err = None
    for attempt in range(4):
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=400,
                system=[{
                    "type": "text",
                    "text": SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": user_msg}],
            )
            text = resp.content[0].text
            parsed = parse_response(text)
            if parsed is None:
                last_err = f"unparseable: {text[:200]!r}"
                continue
            return parsed
        except (anthropic.APIError, anthropic.RateLimitError) as e:
            last_err = str(e)
            time.sleep(2 ** attempt)
    print(f"  FAILED after retries: {article['slug']}: {last_err}")
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Score at most N new articles")
    parser.add_argument("--newest-first", action="store_true", help="Process newest articles first")
    args = parser.parse_args()

    articles = json.loads(ARTICLES.read_text())
    text_by_slug = json.loads(ARTICLE_TEXT.read_text())
    eligible = [a for a in articles if a.get("article_type") == "article"]
    if args.newest_first:
        eligible.sort(key=lambda a: a.get("published_at") or "", reverse=True)
    else:
        eligible.sort(key=lambda a: a.get("published_at") or "")

    existing = load_existing()
    todo = [a for a in eligible if a["slug"] not in existing]
    if args.limit:
        todo = todo[: args.limit]

    print(f"eligible: {len(eligible)}; already scored: {len(existing)}; will score: {len(todo)}")
    if not todo:
        return 0

    client = anthropic.Anthropic()

    fields = ["slug", "title", "published_at", "primary_author",
              "score", "has_policy_rec", "policy_ask", "target",
              "rationale", "model", "scored_at"]
    # Open in append mode if file exists, write header otherwise
    first = not OUT.exists()
    with OUT.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if first:
            writer.writeheader()

        for i, a in enumerate(todo, 1):
            body = text_by_slug.get(a["slug"], "")
            result = score_article(client, a, body)
            if result is None:
                continue
            row = {
                "slug": a["slug"],
                "title": a["title"],
                "published_at": (a.get("published_at") or "")[:10],
                "primary_author": a.get("primary_author", ""),
                "score": result.get("score"),
                "has_policy_rec": result.get("has_policy_rec", ""),
                "policy_ask": result.get("policy_ask") or "",
                "target": result.get("target") or "",
                "rationale": result.get("rationale", ""),
                "model": MODEL,
                "scored_at": time.strftime("%Y-%m-%d"),
            }
            writer.writerow(row)
            f.flush()
            if i % 25 == 0 or i == len(todo):
                print(f"  [{i}/{len(todo)}] {a['slug'][:50]:<50}  score={result.get('score')}")

    print(f"\nWrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
