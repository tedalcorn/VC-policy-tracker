#!/usr/bin/env python3
"""Auto-populate policy_tracking.csv with AI-suggested policy asks.

For each article that the AI scored >= 3 (i.e., has_policy_rec is "yes" or
"partial"), copies the AI's policy_ask into rec_summary and the AI's target
into agencies. Sets has_policy_rec accordingly.

NEVER clobbers a row whose has_policy_rec is already set to something other
than "unreviewed" — those are user-curated and stay intact.

Run anytime after the scorer to refresh; safe to re-run.
"""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCORES = ROOT / "data" / "processed" / "policy_scores.csv"
POLICY = ROOT / "policy_tracking.csv"


def main() -> int:
    if not SCORES.exists():
        print(f"No scores file at {SCORES}")
        return 1
    with SCORES.open(newline="") as f:
        scores = {r["slug"]: r for r in csv.DictReader(f)}
    with POLICY.open(newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        rows = list(reader)

    populated = preserved = 0
    for r in rows:
        slug = r["slug"]
        if slug not in scores:
            continue
        s = scores[slug]
        # Only bring in yes/partial — AI says "no" pieces have null policy_ask
        if s["has_policy_rec"] not in ("yes", "partial"):
            continue
        # Don't clobber user-curated rows
        current = r.get("has_policy_rec", "")
        if current and current not in ("unreviewed", "ai-draft", ""):
            preserved += 1
            continue
        r["has_policy_rec"] = s["has_policy_rec"]
        r["rec_summary"] = s["policy_ask"]
        r["agencies"] = s["target"]
        r["notes"] = f"AI-auto-populated 2026-05-20 (score {s['score']})"
        populated += 1

    with POLICY.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    print(f"populated: {populated}")
    print(f"preserved (user-curated): {preserved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
