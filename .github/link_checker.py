#!/usr/bin/env python3

import os
import json
import argparse
import requests
import html
import urllib3
from datetime import datetime, timezone
from urllib.parse import urlparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib3.exceptions import InsecureRequestWarning

urllib3.disable_warnings(InsecureRequestWarning)

# -------------------------------------------------------------------
# Config
# -------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent

COLLECTIONS_PATH = SCRIPT_DIR / "collections"
INDICATORS_PATH = SCRIPT_DIR / "indicators"

OUTPUT_HTML = SCRIPT_DIR / "link_check_report.html"
KNOWN_ISSUES_FILE = SCRIPT_DIR / "extracted_links.txt"

# History (Part 3) — workflow checks out `results_ci_checks` branch into ./health_history
HISTORY_DIR = Path(os.environ.get("HISTORY_DIR", SCRIPT_DIR.parent / "health_history"))
HISTORY_PREFIX = "health_report_"

TIMEOUT = 10
MAX_WORKERS = 20


# -------------------------------------------------------------------
# Normalize URL
# -------------------------------------------------------------------
def normalize(url: str) -> str:
    if not url:
        return ""
    url = html.unescape(url.strip())
    if not url.startswith("http"):
        return ""
    p = urlparse(url)
    netloc = p.netloc.lower().replace("www.", "")
    path = p.path.rstrip("/")
    return f"{netloc}{path}"


def domain_only(url: str) -> str:
    if not url:
        return ""
    p = urlparse(url)
    return p.netloc.lower().replace("www.", "")


# -------------------------------------------------------------------
# Load known links
# -------------------------------------------------------------------
def load_known_urls(file_path):
    known_full = set()
    known_domains = set()

    if not file_path.exists():
        print(f"⚠️ Missing file: {file_path}")
        return known_full, known_domains

    with open(file_path, "rb") as f:
        for raw_line in f:
            url = raw_line.decode("utf-8", errors="ignore")
            url = (
                url.replace("\ufeff", "")
                   .replace("\r", "")
                   .replace("\n", "")
                   .replace("\t", "")
                   .strip()
            )
            if not url:
                continue
            n = normalize(url)
            d = domain_only(url)
            if n:
                known_full.add(n)
            if d:
                known_domains.add(d)

    print(f"📚 Loaded {len(known_full)} URLs")
    print(f"📚 Loaded {len(known_domains)} domains")
    return known_full, known_domains


KNOWN_FULL, KNOWN_DOMAINS = load_known_urls(KNOWN_ISSUES_FILE)


# -------------------------------------------------------------------
# Check URL
# -------------------------------------------------------------------
def check_url(task):
    file_key, name, url = task
    try:
        r = requests.get(url, allow_redirects=True, timeout=TIMEOUT, verify=False)
        return file_key, name, r.url, r.status_code
    except requests.RequestException:
        return file_key, name, url, "ERR"


# -------------------------------------------------------------------
# Extract links recursively
# -------------------------------------------------------------------
def extract_links(data, skip_key="Resources"):
    results = []
    if isinstance(data, dict):
        for key, value in data.items():
            if key.lower() == skip_key.lower():
                continue
            if isinstance(value, str) and value.startswith("http"):
                results.append((key, value))
            results.extend(extract_links(value, skip_key))
    elif isinstance(data, list):
        for item in data:
            results.extend(extract_links(item, skip_key))
    return results


# -------------------------------------------------------------------
# Suspicious logic
# -------------------------------------------------------------------
def is_suspicious(url, status):
    if status == 200:
        return False
    n = normalize(url)
    d = domain_only(url)
    if n in KNOWN_FULL:
        return False
    if d in KNOWN_DOMAINS:
        return False
    return True


# -------------------------------------------------------------------
# HTML writer
# -------------------------------------------------------------------
def write_html(groups):
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write("""
<html>
<head>
<meta charset="UTF-8">
<title>Link Checker Report</title>
<style>
body { font-family: Arial, sans-serif; line-height: 1.5; padding: 20px; }
.file { font-weight: bold; font-size: 1.2em; margin-top: 25px; border-bottom: 1px solid #ddd; padding-bottom: 5px; }
.entry { margin-left: 15px; padding: 2px 0; }
.green { color: green; }
.red { color: red; }
.gold { color: goldenrod; }
.purple { color: purple; font-weight: bold; }
</style>
</head>
<body>
<h2>Link Checker Report</h2>
<p>Purple = new suspicious links not found in extracted_links.txt</p>
""")
        for file, entries in groups.items():
            f.write(f'<div class="file">{html.escape(file)}</div>\n')
            for name, url, status in entries:
                suspicious = is_suspicious(url, status)
                if suspicious:
                    color, tag = "purple", " ⚠️ SUSPICIOUS"
                elif status == 200:
                    color, tag = "green", ""
                elif status in (301, 302, 307, 308, 403, 405):
                    color, tag = "gold", ""
                else:
                    color, tag = "red", ""
                text = f"{name}: {url} [{status}]{tag}"
                f.write(f'<div class="entry {color}">{html.escape(text)}</div>\n')
        f.write("</body></html>")


# -------------------------------------------------------------------
# Collect tasks
# -------------------------------------------------------------------
def collect(path):
    tasks = []
    if not path.exists():
        return tasks
    for root, _, files in os.walk(path):
        for file in files:
            if not file.endswith(".json"):
                continue
            fp = os.path.join(root, file)
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            for name, url in extract_links(data):
                tasks.append((file, name, url))
    return tasks


def collect_from_files(file_paths):
    tasks = []
    for fp in file_paths:
        p = Path(fp)
        if not p.exists() or not p.is_file():
            print(f"⚠️ Skipping missing file: {fp}")
            continue
        if p.suffix.lower() != ".json":
            continue
        parts = {part.lower() for part in p.parts}
        if "collections" not in parts and "indicators" not in parts:
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"⚠️ Could not parse {fp}: {e}")
            continue
        for name, url in extract_links(data):
            tasks.append((p.name, name, url))
    return tasks


# -------------------------------------------------------------------
# History helpers (Part 3)
# -------------------------------------------------------------------
def load_previous_report():
    """Return the most recent health_report_*.json as a dict, or None."""
    if not HISTORY_DIR.exists():
        return None
    files = sorted(HISTORY_DIR.glob(f"{HISTORY_PREFIX}*.json"))
    if not files:
        return None
    try:
        with open(files[-1], "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ Could not read previous report: {e}")
        return None


def write_new_report(total_checked, broken_links, ok_links):
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = HISTORY_DIR / f"{HISTORY_PREFIX}{ts}.json"
    payload = {
        "timestamp_utc": ts,
        "total_checked": total_checked,
        "errors": len(broken_links),
        "broken_links": sorted(broken_links),
        "ok_links": sorted(ok_links),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"📝 Wrote {path}")
    return path


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Link checker")
    parser.add_argument(
        "--files",
        nargs="*",
        default=None,
        help="Specific JSON files to check (PR mode). If omitted, runs full audit.",
    )
    args = parser.parse_args()

    full_audit_env = os.environ.get("FULL_AUDIT", "").strip() == "1"
    is_pr_mode = args.files is not None and not full_audit_env

    print("\n🚀 Running link checker")

    # ---------------------------------------------------------------
    # PR MODE: only report links that were 200 previously and now aren't
    # ---------------------------------------------------------------
    if is_pr_mode:
        print(f"📄 PR mode — checking {len(args.files)} changed file(s)")
        tasks = collect_from_files(args.files)
        print(f"\n🔗 Total links in changed files: {len(tasks)}")

        prev = load_previous_report()
        prev_ok = set(prev.get("ok_links", [])) if prev else set()
        if not prev_ok:
            print("ℹ️ No previous baseline found — nothing to compare against.")
            write_html({})
            return

        # Only re-check links that were OK last time
        tasks = [t for t in tasks if t[2] in prev_ok]
        print(f"🔁 Re-checking {len(tasks)} previously-OK links")

        if not tasks:
            print("✅ No previously-OK links touched.")
            write_html({})
            return

        groups = {}
        regressions = []

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = [ex.submit(check_url, t) for t in tasks]
            for future in as_completed(futures):
                file, name, url, status = future.result()
                groups.setdefault(file, []).append((name, url, status))
                if status != 200:
                    regressions.append((file, name, url, status))
                    print(f"❌ REGRESSION: {status} {url}  ({file})")

        write_html(groups)

        print("\n--- PR check summary ---")
        print(f"Previously-OK links re-checked: {len(tasks)}")
        print(f"Regressions (200 → not 200):    {len(regressions)}")

        if regressions:
            print("FAIL: links that previously worked are now broken.")
            raise SystemExit(1)
        print("OK: no regressions.")
        return

    # ---------------------------------------------------------------
    # FULL AUDIT MODE
    # ---------------------------------------------------------------
    print("📂 Full audit mode — checking collections/ and indicators/")
    tasks = collect(COLLECTIONS_PATH) + collect(INDICATORS_PATH)
    print(f"\n🔗 Total links: {len(tasks)}")

    if not tasks:
        print("✅ Nothing to check.")
        write_html({})
        return

    groups = {}
    broken_links = set()
    ok_links = set()
    suspicious_count = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = [ex.submit(check_url, t) for t in tasks]
        for future in as_completed(futures):
            file, name, url, status = future.result()
            groups.setdefault(file, []).append((name, url, status))
            if status == 200:
                ok_links.add(url)
            else:
                broken_links.add(url)
            if is_suspicious(url, status):
                suspicious_count += 1
                print(f"⚠️ SUSPICIOUS: {status} {url}")

    write_html(groups)

    # History compare
    prev = load_previous_report()
    prev_broken = set(prev.get("broken_links", [])) if prev else set()
    prev_errors = prev.get("errors") if prev else None

    write_new_report(total_checked=len(tasks), broken_links=broken_links, ok_links=ok_links)

    curr_errors = len(broken_links)
    newly_broken = broken_links - prev_broken
    fixed = prev_broken - broken_links

    print("\n--- Health trend ---")
    print(f"Previous errors: {prev_errors if prev_errors is not None else 'n/a (first run)'}")
    print(f"Current errors:  {curr_errors}")
    print(f"Suspicious:      {suspicious_count}")
    print(f"Fixed since last run:        {len(fixed)}")
    print(f"Newly broken since last run: {len(newly_broken)}")

    if newly_broken:
        print("\n--- Newly broken links ---")
        for u in sorted(newly_broken):
            print(f"  • {u}")

    if prev_errors is not None and curr_errors > prev_errors:
        print(f"\n❌ FAIL: errors increased ({prev_errors} → {curr_errors})")
        raise SystemExit(1)

    print("\n✅ OK: error count did not increase.")


if __name__ == "__main__":
    main()
