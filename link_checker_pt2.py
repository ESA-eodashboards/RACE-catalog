#!/usr/bin/env python3

import os
import json
import argparse
import requests
import html
import urllib3

from urllib.parse import urlparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib3.exceptions import InsecureRequestWarning

# -------------------------------------------------------------------
# Suppress SSL warnings
# -------------------------------------------------------------------
urllib3.disable_warnings(InsecureRequestWarning)

# -------------------------------------------------------------------
# Config
# -------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent

COLLECTIONS_PATH = SCRIPT_DIR / "collections"
INDICATORS_PATH = SCRIPT_DIR / "indicators"

OUTPUT_HTML = SCRIPT_DIR / "results_link_checker.html"

# ✅ file is in parent directory
KNOWN_ISSUES_FILE = SCRIPT_DIR.parent / "extracted_links.txt"

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


# -------------------------------------------------------------------
# Domain helper
# -------------------------------------------------------------------
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
        r = requests.get(
            url,
            allow_redirects=True,
            timeout=TIMEOUT,
            verify=False,
        )
        final_url = r.url
        return file_key, name, final_url, r.status_code

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
                    color = "purple"
                    tag = " ⚠️ SUSPICIOUS"
                elif status == 200:
                    color = "green"
                    tag = ""
                elif status in (301, 302, 307, 308, 403, 405):
                    color = "gold"
                    tag = ""
                else:
                    color = "red"
                    tag = ""

                text = f"{name}: {url} [{status}]{tag}"
                f.write(f'<div class="entry {color}">{html.escape(text)}</div>\n')

        f.write("</body></html>")


# -------------------------------------------------------------------
# Collect tasks (full audit — walks collections/ and indicators/)
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


# -------------------------------------------------------------------
# Collect tasks from a specific list of files (PR mode)
# -------------------------------------------------------------------
def collect_from_files(file_paths):
    tasks = []

    for fp in file_paths:
        p = Path(fp)

        if not p.exists() or not p.is_file():
            print(f"⚠️ Skipping missing file: {fp}")
            continue

        if p.suffix.lower() != ".json":
            continue

        # Only check files inside collections/ or indicators/
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

    print("\n🚀 Running link checker")

    if args.files:
        print(f"📄 PR mode — checking {len(args.files)} changed file(s)")
        tasks = collect_from_files(args.files)
    else:
        print("📂 Full audit mode — checking collections/ and indicators/")
        tasks = collect(COLLECTIONS_PATH) + collect(INDICATORS_PATH)

    print(f"\n🔗 Total links: {len(tasks)}")

    if not tasks:
        print("✅ Nothing to check.")
        write_html({})
        return

    groups = {}
    suspicious_count = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = [ex.submit(check_url, t) for t in tasks]

        for future in as_completed(futures):
            file, name, url, status = future.result()

            groups.setdefault(file, []).append((name, url, status))

            if is_suspicious(url, status):
                suspicious_count += 1
                print(f"⚠️ SUSPICIOUS: {status} {url}")

    write_html(groups)

    print("\n✅ Done")
    print(f"⚠️ Suspicious count: {suspicious_count}")


if __name__ == "__main__":
    main()
