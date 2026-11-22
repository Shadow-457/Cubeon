#!/usr/bin/env python3
"""
release_version.py - the one place that decides "which version is this push?".

The release pipeline (`.github/workflows/build.yml`) publishes a NEW release on
every push to main/master, so something has to name that release. That
something is this script, because the rule has a sharp edge:

  * `cubeon/updater.py::APP_VERSION` is the version the *app* reports, and the
    updater only accepts a release whose tag matches `vX.Y.Z`. If the tag and
    the compiled-in string disagree, every user is told an update is available
    forever, no matter how many times they update. `packaging/build_deb.py` and
    `build_windows_installer.py` also regex APP_VERSION out of the SOURCE, so
    whatever the workflow stamps into the tree is what ships in the .deb and
    the installer's Properties dialog.
  * Therefore `stamp` is the only supported way to set the version, and it is
    run by every build job *before* the build, never by hand.

Policy (`next`):
  * if `v{APP_VERSION}` is not a tag yet -> that version (a maintainer edits
    APP_VERSION to declare a release, including the start of a new minor
    series, e.g. 1.3.0);
  * otherwise -> the highest of (APP_VERSION, every v* tag) with the patch
    bumped (1.3.0 -> 1.3.1 -> 1.3.2 ...), which is what makes a release per
    push automatic and what makes a re-run of an already-tagged commit
    idempotent (the workflow reuses the tag it finds, it does not mint one).

Release channels (2026-10-24):
  * a STABLE is a minor release - patch zero, e.g. 1.3.0 or 1.4.0. It is
    published as a normal GitHub release, becomes `/releases/latest` (which
    feeds the home page, the download Worker and the default updater), and is
    the only channel allowed to stamp its version into the website;
  * explicitly promoted versions in STABLE_PROMOTIONS are also stable;
    maintainers may promote a verified beta without changing its version;
  * everything else is a BETA - 1.3.1, 1.3.2, ... - published as a GitHub
    PRERELEASE. GitHub keeps prereleases out of `/releases/latest`, so a beta
    is invisible on the home page and to stable users by construction, while
    the app's optional beta channel (cubeon/updater.py) can still see it;
  * the site therefore keeps showing the last stable while betas ship, and a
    stable starts the cycle again by editing APP_VERSION to the next X.Y.0.

Versions are compared NUMERICALLY per segment - "1.2.10" must beat "1.2.9",
which a plain string sort gets wrong.

CLI:
  python3 tools/release_version.py next                    # version for this push
  python3 tools/release_version.py next --tags v1.1.2      # ... from explicit tags
  python3 tools/release_version.py current                 # APP_VERSION in the tree
  python3 tools/release_version.py channel 1.3.1           # "stable" or "beta"
  python3 tools/release_version.py bump 1.2.9              # -> 1.2.10
  python3 tools/release_version.py stamp 1.2.1             # rewrite APP_VERSION (+ site if stable)
  python3 tools/release_version.py stamp 1.3.1 --no-site   # beta: APP_VERSION only
  python3 tools/release_version.py stamp 1.2.1 --check     # report only, change nothing
  python3 tools/release_version.py asset linux             # versioned AppImage filename
"""
from __future__ import annotations

import argparse
import json
import re
import runpy
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UPDATER = ROOT / "cubeon" / "updater.py"
# Load this dependency-free contract without initializing the launcher package.
_metadata = runpy.run_path(str(UPDATER))
RELEASE_ASSETS = _metadata["RELEASE_ASSETS"]
release_asset_name = _metadata["release_asset_name"]

# Files whose *display* text carries the version. The download worker resolves
# release assets by the release version, so these
# are cosmetic - a stale one is ugly, not broken.
SITE_FILES = tuple(
    (ROOT / "web" / filename, pattern, replacement)
    for filename, pattern, replacement in (
        ("index.html", re.compile(r"(?<![\w.])v\d+\.\d+\.\d+(?![\w.])"),
         "v{version}"),
        ("download.html", re.compile(
            r"(?<![\w.])(Version )\d+\.\d+\.\d+(?![\w.])"),
         r"\g<1>{version}"),
    )
)

# Explicit maintainer promotion; keep this history so a rebuild retains its channel.
STABLE_PROMOTIONS = frozenset({"1.3.27", "1.3.28", "1.3.38", "1.3.45", "1.4.20", "1.4.50"})

# Mirrors cubeon/updater.py::_TAG_RE: a release the updater can compare against.
# Anything else (nightly, v1.2, v1.2.0-rc1) is not a candidate version.
TAG_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")

# Mirrors packaging/build_deb.py + build_windows_installer.py, which read the
# same literal with their own regex. Anchored to the start of a line on
# purpose: a mention inside a docstring or a comment is not the assignment, and
# counting one as "a second APP_VERSION" would make the stamp refuse to run.
_APP_VERSION_RE = re.compile(r'^(APP_VERSION\s*=\s*")([^"]+)(")', re.MULTILINE)


class VersionError(Exception):
    """Bad input, or a tree that no longer looks like this tool expects."""


# ------------------------------------------------------------------ versioning ---
def parse(text: str) -> tuple[int, int, int] | None:
    """'v1.2.3'/'1.2.3' -> (1, 2, 3); anything else -> None."""
    m = TAG_RE.match((text or "").strip())
    return tuple(int(g) for g in m.groups()) if m else None  # type: ignore[return-value]


def fmt(version: tuple[int, int, int]) -> str:
    return ".".join(str(p) for p in version)


def channel(version: str) -> str:
    """'stable' for patch 0 or an explicit promotion, otherwise 'beta'.

    By default, 1.3.0 is a stable, 1.3.1
    is the first beta after it, 1.3.2 the next, and 1.4.0 starts a new stable.
    GitHub's prerelease flag (set by the workflow from this answer) is what
    hides betas from `/releases/latest`, so the home page and the stable
    updater never need to know they exist.
    """
    parsed = parse(version)
    if parsed is None:
        raise VersionError(f"not a vX.Y.Z version: {version!r}")
    return "stable" if parsed[2] == 0 or fmt(parsed) in STABLE_PROMOTIONS else "beta"


def bump(version: str) -> str:
    """Patch+1: '1.2.9' -> '1.2.10' (the reason for numeric, not string, order)."""
    parsed = parse(version)
    if parsed is None:
        raise VersionError(f"not a vX.Y.Z version: {version!r}")
    return fmt((parsed[0], parsed[1], parsed[2] + 1))


def releasable(tags) -> list[tuple[int, int, int]]:
    return [p for p in (parse(t) for t in tags) if p]


def next_version(source_version: str, tags) -> str:
    """The version the CURRENT push releases. See the module docstring."""
    source = parse(source_version)
    if source is None:
        raise VersionError(
            f"APP_VERSION is not a vX.Y.Z version: {source_version!r} "
            "(the updater can't compare against it and no tag would match it)")
    known = releasable(tags)
    highest_tag = max(known) if known else None
    if source not in known and (highest_tag is None or source > highest_tag):
        # Declared and ahead of everything released: honour it verbatim. This
        # is how a new series starts (APP_VERSION = "1.2.0" -> v1.2.0 next).
        return fmt(source)
    # Already out (a re-push, or the maintainer forgot to bump), or stale
    # (behind the newest tag - a working-tree stamp that never got committed):
    # step past the highest, never backwards. max() compares segments
    # NUMERICALLY, so 1.2.10 > 1.2.9 and string order can't be used here.
    highest = max([source, *known])
    return fmt((highest[0], highest[1], highest[2] + 1))


# ------------------------------------------------------------------ the tree ---
def read_app_version(path: Path = UPDATER) -> str:
    """APP_VERSION as written in the SOURCE (never import: the release job, the
    .deb builder and the installer all read the literal for the same reason -
    no flet/requests on the path)."""
    try:
        src = path.read_text(encoding="utf-8")
    except OSError as ex:
        raise VersionError(f"cannot read {path}: {ex}") from ex
    hits = _APP_VERSION_RE.findall(src)
    if len(hits) != 1:
        raise VersionError(
            f"expected exactly one APP_VERSION = \"...\" in {path}, found "
            f"{len(hits)} - the release stamp can't guess which one is real")
    return hits[0][1]


def git_tags(repo: Path = ROOT) -> list[str]:
    """Every tag git knows about, or [] when this isn't a work tree (a source
    tarball still has to be stampable)."""
    try:
        out = subprocess.run(["git", "-C", str(repo), "tag", "-l", "v*"],
                             capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def stamp(version: str, root: Path = ROOT, check: bool = False,
          site: bool | None = None) -> list[tuple[Path, int]]:
    """Write `version` into APP_VERSION and (for a stable) the site's text.

    Returns [(path, replacements)] for the files that changed (or would change
    with check=True). APP_VERSION is load-bearing, so a tree where it can't be
    found raises: a silent no-op here ships a binary that nags every user
    forever while its release tag says something else.

    `site` defaults to "only for a stable". A beta must not move the website's
    version: the site advertises the download the home page actually serves,
    and that is always the last stable (`/releases/latest` excludes
    prereleases). Pass site=True/False to override (the CLI's --site/--no-site).
    """
    if parse(version) is None:
        raise VersionError(f"refusing to stamp a non vX.Y.Z version: {version!r}")
    if site is None:
        site = channel(version) == "stable"

    editors: list[tuple[Path, re.Pattern, str]] = [
        (UPDATER, _APP_VERSION_RE, r"\g<1>{version}\g<3>"),
        *(SITE_FILES if site else ()),
    ]
    changed: list[tuple[Path, int]] = []
    for path, pattern, template in editors:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as ex:
            if path == UPDATER:
                raise VersionError(f"cannot read {path}: {ex}") from ex
            continue  # optional cosmetic file
        new, count = pattern.subn(template.format(version=version), text)
        if path == UPDATER and count == 0:
            # Load-bearing: read_app_version() would also fail, but say it here
            # too - a stamp that quietly changes nothing releases a build whose
            # APP_VERSION contradicts its own tag, which nags users forever.
            raise VersionError(
                f"no APP_VERSION = \"...\" to stamp in {path} - the release "
                "would ship with the wrong version baked in")
        if count == 0 or new == text:
            continue
        if not check:
            path.write_text(new, encoding="utf-8")
        changed.append((path, count))
    return changed


# ------------------------------------------------------------------------ cli ---
def _cmd_next(args) -> int:
    source = args.source or read_app_version()
    tags = args.tags.split(",") if args.tags else git_tags()
    print(next_version(source, tags))
    return 0


def _cmd_current(args) -> int:
    print(read_app_version())
    return 0


def _cmd_channel(args) -> int:
    print(channel(args.version))
    return 0


def _cmd_asset(args) -> int:
    print(release_asset_name(args.kind, args.version or read_app_version()))
    return 0


def _cmd_bump(args) -> int:
    print(bump(args.version))
    return 0


def _cmd_stamp(args) -> int:
    changed = stamp(args.version, check=args.check, site=args.site)
    verb = "would stamp" if args.check else "stamped"
    if not changed:
        print(f"{verb} {args.version}: already current")
        return 0
    for path, count in changed:
        print(f"{verb} {args.version}: {path} ({count} replacement"
              f"{'' if count == 1 else 's'})")
    return 0


def update_manifest(version: str, release: dict, repository: str, release_channel: str) -> dict:
    """Validate the uploaded binaries before creating public update metadata."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise VersionError("invalid GitHub repository")
    if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version):
        raise VersionError("invalid manifest version")
    if not isinstance(release, dict) or release.get("tag_name") != f"v{version}":
        raise VersionError("release tag does not match the manifest version")
    if release_channel not in {"stable", "beta"} or release.get("prerelease") is not (release_channel == "beta"):
        raise VersionError("release channel does not match the draft")
    uploaded = release.get("assets")
    if not isinstance(uploaded, list):
        raise VersionError("release assets are missing")
    # GitHub's draft assets use the release's temporary slug until publication.
    # Verify that exact trusted draft path, but offer the final tagged URL.
    draft_slug = None
    if release.get("draft") is True:
        match = re.fullmatch(re.escape(f"https://github.com/{repository}/releases/tag/")
                             + r"(untagged-[A-Za-z0-9-]+)", release.get("html_url") or "")
        if match:
            draft_slug = match.group(1)
    assets = {}
    for kind in RELEASE_ASSETS:
        name = release_asset_name(kind, version)
        matches = [asset for asset in uploaded if isinstance(asset, dict) and asset.get("name") == name]
        if len(matches) != 1:
            raise VersionError(f"release needs exactly one {name}")
        asset = matches[0]
        size, digest = asset.get("size"), asset.get("digest")
        if asset.get("state") != "uploaded" or type(size) is not int or size <= 0:
            raise VersionError(f"{name} has not finished uploading")
        if not isinstance(digest, str) or not re.fullmatch(r"sha256:[a-fA-F0-9]{64}", digest):
            raise VersionError(f"{name} is missing its GitHub SHA-256 digest")
        url = f"https://github.com/{repository}/releases/download/v{version}/{name}"
        draft_url = (f"https://github.com/{repository}/releases/download/{draft_slug}/{name}"
                     if draft_slug else None)
        if asset.get("browser_download_url") != url and (draft_url is None or asset.get("browser_download_url") != draft_url):
            raise VersionError(f"{name} has an unexpected download URL")
        assets[kind] = {"name": name, "url": url, "size": size, "sha256": digest[7:].lower()}
    return {"schema_version": 1, "version": version, "tag_name": f"v{version}",
            "channel": release_channel, "prerelease": release_channel == "beta", "assets": assets}


def _cmd_manifest(args) -> int:
    try:
        release = json.loads(Path(args.release_json).read_text(encoding="utf-8"))
        manifest = update_manifest(args.version, release, args.repository, args.channel)
        directory = Path(args.output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        output = directory / f"update-{args.version}.json"
        output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as ex:
        raise VersionError(f"cannot generate update metadata: {ex}") from ex
    print(output)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("next", help="version this push releases")
    p.add_argument("--tags", help="comma-separated git tags (default: git tag -l v*)")
    p.add_argument("--source", help="APP_VERSION to use (default: from cubeon/updater.py)")
    p.set_defaults(func=_cmd_next)

    p = sub.add_parser("current", help="APP_VERSION in this tree")
    p.set_defaults(func=_cmd_current)

    p = sub.add_parser("asset", help="versioned release filename")
    p.add_argument("kind", choices=tuple(RELEASE_ASSETS))
    p.add_argument("--version")
    p.set_defaults(func=_cmd_asset)

    p = sub.add_parser("channel", help="'stable' or 'beta' for a version")
    p.add_argument("version")
    p.set_defaults(func=_cmd_channel)

    p = sub.add_parser("bump", help="patch+1 of an explicit version")
    p.add_argument("version")
    p.set_defaults(func=_cmd_bump)

    p = sub.add_parser("stamp", help="write a version into APP_VERSION + the site")
    p.add_argument("version")
    p.add_argument("--check", action="store_true", help="report only, change nothing")
    p.add_argument("--site", dest="site", action="store_true", default=None,
                   help="also stamp the website (default: only for a stable)")
    p.add_argument("--no-site", dest="site", action="store_false",
                   help="leave the website on its current (stable) version")
    p.set_defaults(func=_cmd_stamp, site=None)

    p = sub.add_parser("manifest", help="verify uploaded binaries and write update-<version>.json")
    p.add_argument("version")
    p.add_argument("--release-json", required=True, help="raw GitHub release API response")
    p.add_argument("--repository", required=True)
    p.add_argument("--channel", required=True, choices=("stable", "beta"))
    p.add_argument("--output-dir", default="dist")
    p.set_defaults(func=_cmd_manifest)

    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        return 2
    try:
        return args.func(args)
    except VersionError as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
