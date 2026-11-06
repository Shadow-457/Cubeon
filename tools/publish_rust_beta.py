#!/usr/bin/env python3
"""Verify completed CI artifacts and preview a pinned Rust beta release.

Publishing requires --publish. Existing releases are never overwritten and this
prerelease never replaces the latest stable launcher release.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cubeon.rust_engine import BUILD, VERSION, RELEASE_BASE
REPO = "Shadow-457/Cubeon"
PLATFORMS = {"linux-x86_64", "windows-x86_64"}


def gh_json(*args):
    return json.loads(subprocess.check_output(["gh", *args, "--repo", REPO], text=True))


def verify_archive(path, platform):
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        names = [m.filename for m in members]
        if len(names) != len(set(names)) or sum(m.file_size for m in members) > 1024**3:
            raise ValueError("Invalid runtime archive members or size")
        for item in members:
            name = Path(item.filename.replace("\\", "/"))
            if name.is_absolute() or ".." in name.parts or ":" in item.filename or (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Unsafe runtime archive path")
        runtime = json.loads(archive.read("cubeon-runtime.json"))
        if (runtime.get("engine"), runtime.get("build"), runtime.get("minecraft")) != ("rust", BUILD, VERSION):
            raise ValueError("Wrong Rust build in archive")
        suffix = ".exe" if platform.startswith("windows") else ""
        required = {"cubeon-rust" + suffix, "cubeon-rust-prepare" + suffix,
                    "research-lock.json", "LICENSE", "THIRD_PARTY_NOTICES.md", "exporters/manifest.json"}
        files = runtime.get("files", {})
        if not required.issubset(files) or set(files) | {"cubeon-runtime.json"} != set(names):
            raise ValueError("Incomplete or unexpected runtime files")
        for name, expected in files.items():
            with archive.open(name) as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != expected:
                raise ValueError("Runtime file digest mismatch: " + name)


def prepare(directory, run_id):
    manifest = directory / "cubeon-rust-release-manifest/manifest.json"
    data = json.loads(manifest.read_text())
    if (data.get("engine"), data.get("build"), data.get("minecraft")) != ("rust", BUILD, VERSION) or set(data.get("platforms", {})) != PLATFORMS:
        raise ValueError("Release must contain the pinned Linux and Windows builds")
    run = gh_json("run", "view", str(run_id), "--json", "headSha,status,conclusion,workflowName")
    commit = data.get("source_commit", "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or run != {"headSha": commit, "status": "completed", "conclusion": "success", "workflowName": "Build Cubeon Rust beta artifacts"}:
        raise ValueError("Release manifest does not match a successful Rust build")
    subprocess.run(["git", "diff", "--quiet", commit, "--", "native/cubeon-rust", "tools/build_rust_engine.py", ".github/workflows/rust-beta.yml"], cwd=ROOT, check=True)
    artifacts = [manifest]
    for platform, item in sorted(data["platforms"].items()):
        url = item.get("url", "")
        filename = f"cubeon-rust-{BUILD}-{platform}.zip"
        if url != RELEASE_BASE + "/" + filename:
            raise ValueError("Archive URL does not match the pinned Cubeon release")
        path = directory / ("cubeon-rust-" + platform) / filename
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != item.get("sha256") or path.stat().st_size != item.get("size"):
            raise ValueError("CI archive hash or size mismatch")
        verify_archive(path, platform)
        artifacts.append(path)
    return commit, artifacts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    commit, artifacts = prepare(args.artifact_dir.resolve(), args.run_id)
    tag = RELEASE_BASE.rsplit("/", 1)[-1]
    print(f"Verified Rust beta {tag} from {commit}")
    for path in artifacts:
        print(f"  {path.name}: {path.stat().st_size:,} bytes")
    if not args.publish:
        print("Preview only. Add --publish to create the prerelease with these 3 assets.")
        return
    exists = subprocess.run(["gh", "api", f"repos/{REPO}/releases/tags/{tag}"], capture_output=True, text=True)
    if exists.returncode == 0:
        raise RuntimeError("Release already exists; refusing to overwrite its assets")
    if "404" not in exists.stderr:
        raise RuntimeError("Couldn't check the existing release: " + exists.stderr)
    with tempfile.TemporaryDirectory(prefix="cubeon-rust-release-") as folder:
        notes = Path(folder) / "notes.md"
        notes.write_text(f"Cubeon Rust beta for Minecraft {VERSION}, Windows and Linux x64.\n\nNative runtime and owned exporters only; Minecraft resources are downloaded and prepared locally. Java 25 is required once for preparation.\n\nVerified CI build: https://github.com/{REPO}/actions/runs/{args.run_id}\n")
        subprocess.run(["gh", "release", "create", tag, *map(str, artifacts), "--repo", REPO,
                        "--target", commit, "--title", f"Cubeon Rust {BUILD}", "--prerelease", "--latest=false", "--notes-file", str(notes)], check=True)


if __name__ == "__main__":
    main()
