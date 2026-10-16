#!/usr/bin/env python3
"""
Publish an owner notification to every running Cubeon launcher.

    python notify --headline "Hello" --content "World"

    python notify --headline "Seasonal update" \
                  --content "Winter colors are live." \
                  --url "https://cubeon.run.place/changelog"

WHAT THIS DOES
    POSTs to the /notify route of the cubeon-downloads Cloudflare Worker
    (worker/cubeon-downloads.js), which stores the entry in KV. The next time
    any Cubeon starts, it fetches that entry and shows it once, as a popup in
    the seasonal-greeting style. There is no push and no targeting: every
    install sees it exactly once.

AUTHORISATION
    The Worker rejects an unauthenticated POST with 401. The token is a Worker
    secret (set once with `npx wrangler secret put NOTIFY_TOKEN`) and is NEVER
    in this repository. The publisher looks for it, in order, in:

      1. --token
      2. $CUBEON_NOTIFY_TOKEN
      3. .notify_token      (repo root, .gitignore'd)
      4. ~/.cubeon_notify_token

    Point it somewhere else (a staging Worker, a local mock) with --endpoint or
    $CUBEON_NOTIFY_ENDPOINT.

AGENTS: ASK FIRST. Running this broadcasts a real popup to every Cubeon user
    on the planet - it is not a local test. Use --dry-run to validate the text,
    or tools/test_notify.py to exercise the whole path offline.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_ENDPOINT = "https://cubeon-downloads.hamza-457-shahbaz.workers.dev/notify"

_MAX_FIELD = 4000


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_token(explicit: str | None = None) -> str | None:
    """The publish token, or None - see the module docstring for the order."""
    if explicit:
        return explicit.strip()
    env = (os.environ.get("CUBEON_NOTIFY_TOKEN") or "").strip()
    if env:
        return env
    for path in (os.path.join(_repo_root(), ".notify_token"),
                 os.path.join(os.path.expanduser("~"), ".cubeon_notify_token")):
        try:
            with open(path, encoding="utf-8") as fh:
                value = fh.read().strip()
            if value:
                return value
        except OSError:
            continue
    return None


def build_payload(args) -> dict:
    payload = {"headline": args.headline.strip(), "content": args.content.strip()}
    if args.url:
        payload["url"] = args.url.strip()
    return payload


def validate(payload: dict) -> str | None:
    """A human message when the payload is invalid, else None."""
    for field in ("headline", "content"):
        value = payload.get(field) or ""
        if not value:
            return f"{field} must not be empty"
        if len(value) > _MAX_FIELD:
            return f"{field} is longer than the worker allows ({_MAX_FIELD})"
    url = payload.get("url")
    if url and not url.startswith(("http://", "https://")):
        return "url must start with http:// or https://"
    return None


def send(endpoint: str, token: str, payload: dict, timeout: float = 15.0,
         opener=None):
    """POSTs the payload; returns (status, body-text). Raises on a transport
    error so the CLI can print something useful."""
    open_fn = opener or urllib.request.urlopen
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint, data=data, method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "cubeon-notify-cli",
        })
    try:
        with open_fn(req, timeout=timeout) as resp:
            return getattr(resp, "status", 200), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode("utf-8", "replace")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="notify",
        description="Publish an owner notification to every Cubeon launcher.")
    parser.add_argument("--headline", required=True,
                        help="the bold line at the top of the popup")
    parser.add_argument("--content", required=True,
                        help="the body text of the popup")
    parser.add_argument("--url", default=None,
                        help="optional https link, offered as an Open button")
    parser.add_argument("--endpoint", default=None,
                        help=f"override the /notify URL (default: {DEFAULT_ENDPOINT})")
    parser.add_argument("--token", default=None,
                        help="override the token (else env / .notify_token file)")
    parser.add_argument("--dry-run", action="store_true",
                        help="validate and print the payload, send nothing")
    args = parser.parse_args(argv)

    payload = build_payload(args)
    problem = validate(payload)
    if problem:
        parser.error(problem)

    endpoint = args.endpoint or (os.environ.get("CUBEON_NOTIFY_ENDPOINT") or "").strip() \
        or DEFAULT_ENDPOINT

    if args.dry_run:
        print(f"dry run - POST {endpoint}")
        print(json.dumps(payload, indent=2))
        return 0

    token = find_token(args.token)
    if not token:
        print("no publish token found.\n"
              "  set CUBEON_NOTIFY_TOKEN, or put it in .notify_token "
              "(repo root, gitignored),\n"
              "  or pass --token. Use --dry-run to check the text without one.",
              file=sys.stderr)
        return 2

    try:
        status, body = send(endpoint, token, payload)
    except Exception as err:  # transport-level: DNS, TLS, timeout, offline
        print(f"could not reach {endpoint}: {err}", file=sys.stderr)
        return 1

    if status == 401:
        print("401 unauthorized - the token does not match the Worker's "
              "NOTIFY_TOKEN secret (or it was never set).", file=sys.stderr)
        return 1
    if status == 501:
        print("501 - the Worker has no CUBEON_NOTIFY KV binding yet; see "
              "worker/wrangler-downloads.toml.", file=sys.stderr)
        return 1
    if status != 200:
        print(f"{status}: {body.strip()[:400]}", file=sys.stderr)
        return 1

    print(f"published to {endpoint}: {body.strip()[:400]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
