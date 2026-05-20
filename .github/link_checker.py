#!/usr/bin/env python3
"""
RACE-catalog link checker.

Two modes (controlled by env var FULL_AUDIT):
  - FULL_AUDIT != "1"  -> PR check mode
        Only fails / reports links that used to work (200 in the most recent
        health_report) and now don't return 200.
  - FULL_AUDIT == "1"  -> Full audit mode (bi-weekly)
        Checks every link, writes a new timestamped health_report_*.json into
        health_history/, and fails only if current_errors > previous_errors.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent  # .github/ -> repo root
HISTORY_DIR = REPO_ROOT / "health_history"
HISTORY_BRANCH = "results_ci_checks"
FULL_AUDIT = os.environ.get("FULL_AUDIT") == "1"
TIMEOUT = 15
USER_AGENT = "RACE-catalog-link-checker/1.0"

URL_REGEX = re.compile(r"https?://[^\s\)\]\}\"'>]+")


# ---------------------------------------------------------------------------
# Link discovery + checking
# ---------------------------------------------------------------------------

def find_links() -> list[str]:
    """Walk the repo and pull every http(s) URL out of text-ish files."""
    links: set[str] = set()
    skip_dirs = {".git", "node_modules", "health_history", ".github"}
    exts = {".md", ".markdown", ".txt", ".rst", ".json", ".yml", ".yaml", ".html"}

    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        if path.suffix.lower() not in exts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for match in URL_REGEX.findall(text):
            links.add(match.rstrip(".,);:"))
    return sorted(links)


def check_link(url: str) -> int:
    """Return HTTP status code, or 0 on network/other failure."""
    headers = {"User-Agent": USER_AGENT}
    try:
        r = requests.head(url, allow_redirects=True, timeout=TIMEOUT, headers=headers)
        if r.status_code >= 400 or r.status_code == 405:
            r = requests.get(url, allow_redirects=True, timeout=TIMEOUT, headers=headers)
        return r.status_code
    except requests.RequestException:
        return 0


def check_all(links: list[str]) -> list[dict]:
    results = []
    for i, url in enumerate(links, 1):
        status = check_link(url)
        ok = status == 200
        print(f"[{i}/{len(links)}] {status or 'ERR'}  {url}")
        results.append({"url": url, "status": status, "ok": ok})
    return results


# ---------------------------------------------------------------------------
# History (full-audit only)
# ---------------------------------------------------------------------------

def load_previous_report() -> dict | None:
    """Return the most recent health_report_*.json as a dict, or None."""
    if not HISTORY_DIR.exists():
        return None
    reports = sorted(HISTORY_DIR.glob("health_report_*.json"))
    if not reports:
        return None
    try:
        return json.loads(reports[-1].read_text(encoding="utf-8"))
    except Exception:
        return None


def write_new_report(results: list[dict]) -> Path:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    broken = sorted({r["url"] for r in results if r["status"] != 200})
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "total_checked": len(results),
        "errors": len(broken),
        "broken_links": broken,
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = HISTORY_DIR / f"health_report_{ts}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {out.relative_to(REPO_ROOT)}")
    return out


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def run_pr_check() -> int:
    """
    PR mode: only report links that were 200 in the last health_report
    and are no longer 200 now.
    """
    prev = load_previous_report()
    if not prev:
        print("No previous health_report found — PR check has no baseline, skipping.")
        return 0

    prev_broken = set(prev.get("broken_links", []))
    # Anything in the previous report that wasn't broken was, by definition, working (200).
    # We can only re-check URLs we know about — i.e. the ones currently in the repo.
    current_links = find_links()
    previously_working = [u for u in current_links if u not in prev_broken]

    if not previously_working:
        print("No previously-working links to re-check.")
        return 0

    print(f"Re-checking {len(previously_working)} previously-working links...\n")
    results = check_all(previously_working)
    regressions = [r["url"] for r in results if r["status"] != 200]

    print("\n--- PR check summary ---")
    print(f"Re-checked:  {len(results)}")
    print(f"Regressions: {len(regressions)}")
    if regressions:
        print("\nLinks that worked before and are broken now:")
        for u in regressions:
            print(f"  - {u}")
        return 1
    print("OK — no regressions.")
    return 0


def run_full_audit() -> int:
    links = find_links()
    print(f"Full audit: checking {len(links)} links...\n")
    results = check_all(links)

    prev = load_previous_report()
    write_new_report(results)

    curr_broken = {r["url"] for r in results if r["status"] != 200}
    curr_errors = len(curr_broken)

    print("\n--- Full audit summary ---")
    print(f"Total checked:  {len(results)}")
    print(f"Current errors: {curr_errors}")

    if prev is None:
        print("No previous report — baseline established. PASS.")
        return 0

    prev_broken = set(prev.get("broken_links", []))
    prev_errors = prev.get("errors", len(prev_broken))
    newly_broken = sorted(curr_broken - prev_broken)
    fixed = sorted(prev_broken - curr_broken)

    print(f"Previous errors: {prev_errors}")
    if fixed:
        print(f"\nFixed since last run ({len(fixed)}):")
        for u in fixed:
            print(f"  + {u}")
    if newly_broken:
        print(f"\nNewly broken since last run ({len(newly_broken)}):")
        for u in newly_broken:
            print(f"  - {u}")

    if curr_errors > prev_errors:
        print(f"\nFAIL: errors grew {prev_errors} -> {curr_errors}.")
        return 1
    print(f"\nOK: errors {prev_errors} -> {curr_errors}.")
    return 0


def main() -> int:
    return run_full_audit() if FULL_AUDIT else run_pr_check()


if __name__ == "__main__":
    sys.exit(main())
