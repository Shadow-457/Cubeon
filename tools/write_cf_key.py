#!/usr/bin/env python3
"""
Bake the one shared CurseForge API key into a build.

Cubeon ships **one** CurseForge key for every user (2026-10-18, operator's
decision) instead of asking each player to paste their own. The key cannot live
in the repository, because this repo is public and a committed key is a revoked
key. So it travels as a release secret:

    GitHub  Settings > Secrets  CURSEFORGE_API_KEY
        -> .github/workflows/build.yml runs this script in every build job,
           before PyInstaller, with that secret in the environment
        -> this script writes cubeon/_cf_key.py (gitignored, one line)
        -> PyInstaller compiles it into the frozen bundle
        -> cubeon/modpacks._curseforge_api_key() reads it last, as the
           fallback below an environment variable or a local override file.

Run it by hand with the same variable to give a source checkout a key
(`CURSEFORGE_API_KEY=... python3 tools/write_cf_key.py`), which is how a dev
machine gets the full catalogue without any per-user config.

No secret means a perfectly valid build: the tab shows the curated CurseForge
classics and the provider is simply dormant. This script therefore EXITS 0 in
that case - a missing secret must never fail a release - and deletes any stale
generated file, so a reused checkout can never ship an old key.
"""
import os
import pathlib
import sys

TARGET = pathlib.Path(__file__).resolve().parents[1] / "cubeon" / "_cf_key.py"

HEADER = (
    '"""Generated at build time from the CURSEFORGE_API_KEY secret.\n\n'
    "Do not commit and do not edit: this repository is public, and a committed\n"
    "key is a revoked key. tools/write_cf_key.py writes this file; see\n"
    "cubeon/modpacks._curseforge_api_key() for how it is read.\n"
    '"""\n'
)


def main() -> int:
    key = (os.environ.get("CURSEFORGE_API_KEY") or "").strip()
    if not key:
        # A stale generated file is worse than none: it would outlive the
        # secret (revoked key, or a fork that never had it).
        if TARGET.exists():
            TARGET.unlink()
            print(f"removed stale {TARGET.name}")
        print("CURSEFORGE_API_KEY is not set: this build ships the curated "
              "CurseForge classics only (no API key).")
        return 0
    TARGET.write_text(HEADER + f"BUILTIN_KEY = {key!r}\n", encoding="utf-8")
    # Never print the key itself - this runs in CI logs.
    print(f"wrote {TARGET.name} ({len(key)} characters)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
