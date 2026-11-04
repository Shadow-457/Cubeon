#!/usr/bin/env python3
"""Build/package Cubeon's owned Rust beta; never package Minecraft files.

JDK 25 and verified Minecraft 26.3 inputs are needed to compile our exporter
classes. The installed runtime then needs only Java 25 for local preparation.
This tool creates local artifacts; it never publishes or pushes a release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cubeon.rust_engine import BUILD, VERSION, RELEASE_BASE, platform_tag

SOURCE = ROOT / "native" / "cubeon-rust"
PARITY = Path("mods/cubeon/src/test/java/dev/cubeonlab/parity")


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def package(binary_dir, exporter_dir, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rust-bundle-", dir=destination.parent) as temp:
        stage = Path(temp) / "runtime"
        stage.mkdir()
        suffix = ".exe" if os.name == "nt" else ""
        for name in ("cubeon-rust", "cubeon-rust-prepare"):
            shutil.copy2(binary_dir / (name + suffix), stage)
        for name in ("research-lock.json", "LICENSE", "THIRD_PARTY_NOTICES.md", "README.md"):
            shutil.copy2(SOURCE / name, stage)
        # Embedded fonts/icons and patched libraries retain their license texts.
        license_roots = (SOURCE / "third_party", SOURCE / "crates/cubeon-theme")
        for directory in license_roots:
            for file in directory.rglob("*"):
                if file.is_file() and file.name.startswith(("LICENSE", "OFL-", "COPYING")):
                    target = stage / file.relative_to(SOURCE)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(file, target)
        shutil.copytree(SOURCE / PARITY, stage / PARITY)
        # key() fingerprints these original sources, even with shipped classes.
        compiler = Path("crates/cubeon-prepare/src/exporters.rs")
        (stage / compiler).parent.mkdir(parents=True)
        shutil.copy2(SOURCE / compiler, stage / compiler)
        # Only original exporter classes; exclude temporary inputs/logs/caches.
        for source in exporter_dir.rglob("*"):
            if not source.is_file():
                continue
            relative = source.relative_to(exporter_dir)
            if source.suffix == ".class":
                if not str(relative).replace("\\", "/").startswith(
                        ("client/dev/cubeonlab/parity/", "server/dev/cubeonlab/parity/")):
                    raise ValueError(f"Unexpected exporter class: {relative}")
            elif relative != Path("manifest.json"):
                continue
            target = stage / "exporters" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        if not (stage / "exporters/manifest.json").is_file():
            raise ValueError("Compiled exporter manifest is missing")
        manifest = {"engine": "rust", "build": BUILD, "minecraft": VERSION,
                    "upstream_commit": "33816de710f3c14632ee10be5915fca7240b9754",
                    "files": {p.relative_to(stage).as_posix(): sha256(p)
                              for p in sorted(stage.rglob("*")) if p.is_file()}}
        (stage / "cubeon-runtime.json").write_text(json.dumps(manifest, indent=2) + "\n")
        if destination.exists():
            shutil.rmtree(destination)
        stage.rename(destination)


def archive_bundle(directory):
    archive = directory.parent / f"cubeon-rust-{BUILD}-{directory.name}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for file in sorted(directory.rglob("*")):
            if file.is_file():
                bundle.write(file, file.relative_to(directory).as_posix())
    return {"url": RELEASE_BASE + "/" + archive.name, "sha256": sha256(archive),
            "size": archive.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("release", "fast"), default="release")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--java-home", required=True)
    parser.add_argument("--minecraft-dir", required=True)
    parser.add_argument("--server-jar", required=True)
    parser.add_argument("--exporter-dir", type=Path)
    args = parser.parse_args()
    env = {**os.environ, "CUBEON_RUST_VERSION": BUILD}
    if not args.skip_build:
        subprocess.run(["cargo", "build", "--locked", "--manifest-path", str(SOURCE / "Cargo.toml"),
                        "--profile", args.profile, "--jobs", str(args.jobs), "-p", "cubeon-client",
                        "--bin", "cubeon-rust", "-p", "cubeon-prepare", "--bin", "cubeon-rust-prepare"],
                       env=env, check=True)
    binaries = SOURCE / "target" / args.profile
    exporters = args.exporter_dir
    if exporters is None:
        preparer = binaries / ("cubeon-rust-prepare.exe" if os.name == "nt" else "cubeon-rust-prepare")
        result = subprocess.run([str(preparer), "compile-exporters", "--prepare", "--root", str(SOURCE),
                                 "--java-home", args.java_home, "--minecraft-dir", args.minecraft_dir,
                                 "--server-jar", args.server_jar], capture_output=True, text=True, env=env)
        print(result.stdout, end="")
        if result.returncode:
            raise RuntimeError(result.stderr)
        exporters = Path(result.stdout.strip().splitlines()[-1])
    destination = ROOT / "build/rust-engine" / platform_tag()
    package(binaries, exporters, destination)
    item = archive_bundle(destination)
    manifest = {"engine": "rust", "build": BUILD, "minecraft": VERSION,
                "platforms": {platform_tag(): item}}
    (destination.parent / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Verified bundle: {destination}")
    print(json.dumps(item, indent=2))


if __name__ == "__main__":
    main()
