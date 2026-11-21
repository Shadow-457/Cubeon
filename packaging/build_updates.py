"""Generate/verify incremental release assets; never publish a release itself."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import logging
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cubeon import auto_update as update

log = logging.getLogger(__name__)

_RECONSTRUCT = r'''
import hashlib, importlib.util, json, os, sys, time
spec = importlib.util.spec_from_file_location("patch_decoder", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
started = time.monotonic()
module.apply_patch(sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]))
seconds = time.monotonic() - started
digest = hashlib.sha256()
with open(sys.argv[4], "rb") as stream:
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
if os.name == "nt":
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize",
            "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
            "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.WinDLL("kernel32")
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    peak = counters.PeakWorkingSetSize
else:
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)
print(json.dumps({"sha256": digest.hexdigest(), "reconstruction_seconds": round(seconds, 3),
                  "reconstruction_peak_rss_bytes": peak}))
'''


def reconstruct_measured(base, patch, output, size):
    # A fresh stdlib-only process separates decoder memory from bsdiff's
    # build-time suffix arrays and checks the real runtime implementation.
    result = subprocess.run([sys.executable, "-c", _RECONSTRUCT,
                             str(ROOT / "cubeon/update_patch.py"), str(base), str(patch),
                             str(output), str(size)], check=True, capture_output=True,
                            text=True, timeout=20 * 60)
    return json.loads(result.stdout)


def gh_json(*args):
    result = subprocess.run(["gh", *args], check=True, capture_output=True, text=True, timeout=90)
    return json.loads(result.stdout)


def release_metadata(tag):
    # gh resolves drafts by listing; the public tag endpoint may return 404.
    reference = gh_json("release", "view", tag, "--json", "apiUrl")
    url = reference.get("apiUrl", "")
    if not url.startswith(f"https://api.github.com/repos/{update.REPOSITORY}/releases/"):
        raise ValueError("Unexpected release API reference.")
    return gh_json("api", url)


def published_bases(kind, version, cache):
    """Choose three numeric stable predecessors, not release creation order."""
    pages = gh_json("api", f"repos/{update.REPOSITORY}/releases?per_page=100", "--paginate", "--slurp")
    candidates = []
    for page in pages:
        for data in page:
            try:
                release = update.parse_release(data, kind, "0.0.0")
                if release and update.version_tuple(release.version) < update.version_tuple(version):
                    candidates.append(release)
            except update.UpdateError:
                continue
    candidates.sort(key=lambda item: update.version_tuple(item.version), reverse=True)
    result = []
    for release in candidates:
        try:
            path = update.download_asset(release, cache, cancel=threading.Event())
            update.verify_download(path, release, kind)
            result.append((release.version, path))
            if len(result) == 3:
                break
        except Exception as error:
            log.warning("Cannot prepare base %s: %s", release.version, type(error).__name__)
    return result


def generate(kind, version, target, output, bases=()):
    """Emit an empty manifest when none of the available patches is worthwhile."""
    update.version_tuple(version)
    target, output = Path(target), Path(output)
    update._executable_header(target, kind)
    size, sha = target.stat().st_size, update.file_hash(target)
    if not 1024 <= size <= update.MAX_ASSET:
        raise ValueError("Invalid target artifact size.")
    output.mkdir(parents=True, exist_ok=True)
    for stale in output.glob(f"Cubeon-{kind}-x64-from-v*.bsdiff"):
        if stale.is_file() and not stale.is_symlink():
            stale.unlink()
    patches, measurements = [], []
    ordered = sorted(bases, key=lambda pair: update.version_tuple(pair[0]), reverse=True)[:3]
    seen = set()
    for base_version, base in ordered:
        update.version_tuple(base_version)
        if base_version in seen or update.version_tuple(base_version) >= update.version_tuple(version):
            raise ValueError("Duplicate or non-predecessor patch base.")
        seen.add(base_version)
        base = Path(base)
        patch = output / f"Cubeon-{kind}-x64-from-v{base_version}.bsdiff"
        try:
            if importlib.metadata.version("bsdiff4") != "1.4.4":
                raise ValueError("Install packaging/update-requirements.txt for this build.")
            import bsdiff4
            update._executable_header(base, kind)
            base_sha, base_size = update.file_hash(base), base.stat().st_size
            started = time.monotonic()
            bsdiff4.file_diff(str(base), str(target), str(patch))
            patch_size = patch.stat().st_size
            measurement = {"platform": kind, "base_version": base_version, "target_version": version,
                           "full_bytes": size, "patch_bytes": patch_size,
                           "saved_percent": round(100 * (1 - patch_size / size), 2),
                           "generation_seconds": round(time.monotonic() - started, 3)}
            if patch_size * 10 >= size * 7:
                measurement["published"] = False
                measurements.append(measurement)
                patch.unlink()
                continue
            with tempfile.TemporaryDirectory(prefix="cubeon-patch-verify-", dir=output) as directory:
                reconstructed = Path(directory) / "reconstructed"
                measured = reconstruct_measured(base, patch, reconstructed, size)
                if measured.pop("sha256") != sha:
                    raise ValueError("Generated patch does not reproduce the full release.")
                if measured["reconstruction_peak_rss_bytes"] > 64 * 1024 * 1024:
                    raise ValueError("Patch reconstruction exceeded the memory budget.")
                measurement.update(measured)
            measurement["published"] = True
            measurements.append(measurement)
            patches.append({"name": patch.name, "size": patch_size, "sha256": update.file_hash(patch),
                            "base_size": base_size, "base_sha256": base_sha})
        except Exception as error:
            patch.unlink(missing_ok=True)
            log.warning("Patch generation skipped for %s: %s", base_version, type(error).__name__)
    manifest = {"schema": 1, "platform": kind, "version": version, "format": "BSDIFF40",
                "target": {"name": update.ASSETS[kind], "size": size, "sha256": sha}, "patches": patches}
    body = json.dumps(manifest, indent=2).encode() + b"\n"
    if len(body) > update.MAX_MANIFEST:
        raise ValueError("Update manifest is too large.")
    temporary = output / (update.MANIFESTS[kind] + ".tmp")
    temporary.write_bytes(body)
    temporary.replace(output / update.MANIFESTS[kind])
    (output / f"{kind}-measurements.json").write_text(json.dumps(measurements, indent=2) + "\n")
    return manifest


def verify_published_assets(tag, cache):
    """Verify draft manifests and all referenced uploaded patch digests before publication."""
    data = release_metadata(tag)
    if data.get("tag_name") != tag:
        raise ValueError("Unexpected release tag.")
    staged = dict(data, draft=False, prerelease=False)
    for kind in update.ASSETS:
        release = update.parse_release(staged, kind, "0.0.0")
        if release is None or release.manifest is None:
            raise ValueError(f"Missing verified {kind} update manifest.")
        manifest = download_staged(tag, release.manifest, cache)
        refs = update.parse_manifest(json.loads(manifest.read_bytes()), release, kind)
        for ref, _, _ in refs:
            download_staged(tag, ref, cache)
        print(f"Verified {kind} manifest and {len(refs)} patch assets.")


def download_staged(tag, asset, cache):
    # Browser URLs for draft assets are not public yet. gh uses authenticated
    # release-asset API downloads; still verify every byte against GitHub's digest.
    path = Path(cache) / asset.name
    path.unlink(missing_ok=True)
    subprocess.run(["gh", "release", "download", tag, "--pattern", asset.name,
                    "--dir", str(cache)], check=True, timeout=15 * 60)
    update._verify_asset(path, asset, threading.Event())
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--platform", choices=update.ASSETS, required=True)
    build.add_argument("--version", required=True)
    build.add_argument("--target", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--base", action="append", default=[], metavar="VERSION=FILE")
    build.add_argument("--published-bases", action="store_true")
    verify = commands.add_parser("verify")
    verify.add_argument("--tag", required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    with tempfile.TemporaryDirectory(prefix="cubeon-update-build-") as directory:
        cache = Path(directory)
        if args.command == "verify":
            verify_published_assets(args.tag, cache)
        else:
            bases = [(version, Path(path)) for version, path in (item.split("=", 1) for item in args.base)]
            if args.published_bases:
                try:
                    bases.extend(published_bases(args.platform, args.version, cache))
                except Exception as error:
                    log.warning("Previous releases unavailable; emitting a full-download fallback: %s",
                                type(error).__name__)
            result = generate(args.platform, args.version, args.target, args.output, bases)
            print(f"Generated {args.platform} manifest with {len(result['patches'])} patches.")
            print((args.output / f"{args.platform}-measurements.json").read_text())


if __name__ == "__main__":
    main()
