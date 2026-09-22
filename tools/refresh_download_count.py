#!/usr/bin/env python3
"""Refresh web/assets/download-count.json - the number the site shows.

The website prints "N release downloads" next to the download buttons. The
repository is PRIVATE, so a visitor's browser cannot ask GitHub for that number
(anonymous requests to the API and to /releases/latest both answer 404), and the
Vercel function in `web/api/download-count.js` only answers with a sum once a
`GITHUB_TOKEN` is configured for that deployment.

This script is the credential-free source of truth instead: it runs inside
GitHub Actions, where the workflow's own token can read the repository, and
writes the sum into a small static file that ships with the site. The token
never leaves the runner, and the site keeps working with no hosting config.

Run it by hand:

    GH_TOKEN=$(gh auth token) python3 tools/refresh_download_count.py
    python3 tools/refresh_download_count.py --dry-run     # print only

Exit status: 0 on success (including "nothing changed"), 1 when GitHub could
not be read, so a scheduled run turns red instead of silently going stale.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "web" / "assets" / "download-count.json"
DEFAULT_REPOSITORY = "Shadow-457/Cubeon"
API_ROOT = "https://api.github.com"

# Installer assets the site actually advertises. This is the SAME allow-list as
# DOWNLOAD_ASSETS in web/api/download-count.js - a test keeps the two in sync,
# and leftovers on a release (portable exe, ZIP, .sha256...) must never inflate
# the public number.
DOWNLOAD_ASSETS = (
    "Cubeon-x86_64.AppImage",
    "cubeon_1.0.0_amd64.deb",
    "Cubeon-Linux-x86_64-Setup.sh",
    "Cubeon-Windows-x64-Setup.exe",
)


def _download_count(asset) -> int:
    """One asset's counter, tolerant of a missing/garbage value - never negative."""
    if not isinstance(asset, dict):
        return 0
    raw = asset.get("download_count")
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        return 0
    return raw


def summarize_release(release) -> dict:
    """{'total': int, 'assets': {name: count}} over the advertised installers only."""
    assets = release.get("assets") if isinstance(release, dict) else None
    counts = {}
    total = 0
    for asset in assets if isinstance(assets, list) else []:
        name = asset.get("name") if isinstance(asset, dict) else None
        if name not in DOWNLOAD_ASSETS:
            continue
        count = _download_count(asset)
        counts[name] = count
        total += count
    return {"total": total, "assets": counts}


def build_document(release, repository: str = DEFAULT_REPOSITORY,
                   generated_at=None) -> dict:
    """The JSON document, minus the timestamp unless one is supplied."""
    summary = summarize_release(release)
    document = {
        "total": summary["total"],
        "assets": summary["assets"],
        "release": (release.get("tag_name") or None) if isinstance(release, dict) else None,
        "repository": repository,
    }
    if generated_at:
        document["generated_at"] = generated_at
    return document


def counts_match(existing, document: dict) -> bool:
    """Same numbers? A new `generated_at` alone must never create a commit."""
    if not isinstance(existing, dict):
        return False
    return {key: value for key, value in existing.items()
            if key != "generated_at"} == document


def fetch_latest_release(repository: str = DEFAULT_REPOSITORY, token=None,
                         urlopen=None) -> dict:
    """The latest release, or raise - `urlopen` is injectable for tests."""
    opener = urlopen or urllib.request.urlopen
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "cubeon-download-counter",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(
        f"{API_ROOT}/repos/{repository}/releases/latest", headers=headers)
    with opener(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def render(document: dict) -> str:
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def read_existing(path=OUTPUT_PATH):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Refresh the website's download count.")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the document instead of writing the file")
    args = parser.parse_args(argv)

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repository = os.environ.get("CUBEON_REPO") or DEFAULT_REPOSITORY
    try:
        release = fetch_latest_release(repository, token)
    except urllib.error.HTTPError as exc:
        print(f"GitHub refused the release lookup for {repository}: HTTP {exc.code}. "
              "A private repository needs a token (GH_TOKEN or GITHUB_TOKEN).",
              file=sys.stderr)
        return 1
    except Exception as exc:  # network down, DNS, timeout, unreadable body
        print(f"Could not read {repository} from GitHub: {exc}", file=sys.stderr)
        return 1

    document = build_document(release, repository=repository)
    existing = read_existing(Path(OUTPUT_PATH))
    if counts_match(existing, document):
        print(f"Download count unchanged (total={document['total']}); file left alone.")
        return 0

    document["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    text = render(document)
    if args.dry_run:
        print(text, end="")
        return 0
    output = Path(OUTPUT_PATH)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    try:
        shown = output.relative_to(REPO_ROOT)
    except ValueError:      # a caller (mainly the tests) pointed it elsewhere
        shown = output
    print(f"Wrote {shown}: total={document['total']} release={document['release']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
