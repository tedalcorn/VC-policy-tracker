#!/usr/bin/env python3
"""Orchestrator for the Vital City coverage tracker.

Full pipeline:
    fetch → build_articles → sync_policy_tracking → score_policy_asks
    → extract_supporting_excerpts → auto_populate_policy → build_site

All AI steps are resumable — they skip articles already processed, so on
weeks with no new pieces they're effectively no-ops (no API spend).

Usage:
    python update.py                # full pipeline, no commit
    python update.py --no-fetch     # skip Ghost API call
    python update.py --no-ai        # skip AI scoring/extraction steps
    python update.py --push         # also git commit + push when changes exist
                                    # (used by the daily launchd job)
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"


def run(name: str, *args: str) -> None:
    print(f"\n=== {name} ===")
    cmd = [sys.executable, str(SCRIPTS / name), *args]
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode:
        raise SystemExit(f"{name} failed with code {result.returncode}")


def commit_and_push() -> None:
    """Commit any pending changes and push to origin.

    Important: invoke git via Python's subprocess (not bash) — macOS TCC
    blocks bash-spawned git from reading .git/ inside ~/Desktop/ (see
    feedback-launchd-git-desktop-tcc). Python subprocess from a launchd-
    triggered job works around it. Same pattern as the NYT daily updater.
    """
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    if not status.stdout.strip():
        print("\n=== push ===\nno changes to commit")
        return
    today = time.strftime("%Y-%m-%d")
    print(f"\n=== push ({today}) ===")
    subprocess.run(["git", "add", "-A"], cwd=ROOT, check=True)
    subprocess.run(
        ["git", "commit", "-m", f"Auto-update {today}: fresh Vital City fetch"],
        cwd=ROOT, check=True,
    )
    subprocess.run(["git", "push"], cwd=ROOT, check=True)
    print("pushed.")


def main() -> int:
    args = sys.argv[1:]
    skip_fetch = "--no-fetch" in args
    skip_ai = "--no-ai" in args
    push = "--push" in args

    if not skip_fetch:
        run("fetch.py")
    run("build_articles.py")
    run("sync_policy_tracking.py")
    if not skip_ai:
        run("score_policy_asks.py")
        run("extract_supporting_excerpts.py")
        run("auto_populate_policy.py")
    run("build_site.py")

    if push:
        commit_and_push()

    print("\nDone. Serve with:  cd docs && python -m http.server 8000")
    return 0


if __name__ == "__main__":
    sys.exit(main())
