#!/usr/bin/env python3
"""For each scored article, extract a verbatim 1-4 sentence passage from the
article body that most clearly states or supports the inferred recommendation.

Only processes articles with score >= 3 (i.e., those with a real policy_ask).
Output: data/processed/policy_excerpts.csv (slug, supporting_excerpt).
Resumable — skips slugs already extracted.
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
from pathlib import Path

import anthropic

ROOT = Path(__file__).resolve().parent.parent
SCORES = ROOT / "data" / "processed" / "policy_scores.csv"
TEXT = ROOT / "data" / "processed" / "articles_text.json"
OUT = ROOT / "data" / "processed" / "policy_excerpts.csv"

MODEL = "claude-haiku-4-5-20251001"

SYSTEM = """You extract a supporting quotation from a Vital City article.

You will receive:
- the article body
- the policy recommendation that an earlier analysis inferred from it

Return 1-4 SENTENCES, VERBATIM from the article, that most clearly state or
support that recommendation. No quotation marks. No paraphrasing. No preamble.
If the recommendation is implicit rather than stated, return the sentence(s)
that come closest, and prefix the response with "[closest]: " (one space after).
If multiple non-adjacent sentences best capture it together, return them
separated by " ... ".
Keep total length under ~600 characters."""


def main() -> int:
    scores = list(csv.DictReader(SCORES.open(newline="")))
    text_by_slug = json.loads(TEXT.read_text())

    existing = {}
    if OUT.exists():
        with OUT.open(newline="") as f:
            existing = {r["slug"]: r["supporting_excerpt"] for r in csv.DictReader(f)}

    todo = [s for s in scores if int(s["score"]) >= 3 and s["slug"] not in existing]
    print(f"to extract: {len(todo)} (already done: {len(existing)})")

    client = anthropic.Anthropic()
    rows = [{"slug": s, "supporting_excerpt": e} for s, e in existing.items()]

    def write_out():
        with OUT.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["slug","supporting_excerpt"])
            w.writeheader(); w.writerows(rows)

    for i, s in enumerate(todo, 1):
        slug = s["slug"]
        body = (text_by_slug.get(slug) or "")[:6000]
        if not body:
            continue
        msg = (f"Inferred policy recommendation: {s['policy_ask']}\n\n"
               f"Article body:\n{body}")
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=400,
                system=[{
                    "type": "text",
                    "text": SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": msg}],
            )
            excerpt = resp.content[0].text.strip()
            # Strip wrapping quotes if the model added them despite instructions
            excerpt = re.sub(r'^["“]+|["”]+$', "", excerpt)
            rows.append({"slug": slug, "supporting_excerpt": excerpt})
            if i % 25 == 0 or i == len(todo):
                write_out()
                print(f"  [{i}/{len(todo)}] {slug[:50]}")
        except Exception as e:
            print(f"  failed {slug}: {e}")
            time.sleep(2)

    write_out()
    print(f"\nwrote {len(rows)} rows to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
