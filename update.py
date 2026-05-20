#!/usr/bin/env python3
"""Orchestrator: refetch Ghost, rebuild articles, sync policy CSV, build site.

Usage:
    python update.py             # full pipeline
    python update.py --no-fetch  # skip Ghost API call, reuse cached raw JSON
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"


def run(name: str, *args: str) -> None:
    print(f"\n=== {name} ===")
    cmd = [sys.executable, str(SCRIPTS / name), *args]
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode:
        raise SystemExit(f"{name} failed with code {result.returncode}")


def main() -> int:
    skip_fetch = "--no-fetch" in sys.argv
    if not skip_fetch:
        run("fetch.py")
    run("build_articles.py")
    run("sync_policy_tracking.py")
    run("build_site.py")
    print("\nDone. Serve with:  cd site && python -m http.server 8000")
    return 0


if __name__ == "__main__":
    sys.exit(main())
