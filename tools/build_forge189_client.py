#!/usr/bin/env python3
"""Build Cubeon Client for Forge 1.8.9 with Java 8 bytecode and SRG references.

Minecraft build inputs stay in build/ and never enter the distributable mod.
Public Forge/MCP inputs can be fetched explicitly with --download-inputs.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build/forge-1.8.9"
INPUTS = WORK / "inputs"
SOURCE = ROOT / "mod/forge189/src/main"
URLS = {
    "forge-universal.jar": "https://maven.minecraftforge.net/net/minecraftforge/forge/1.8.9-11.15.1.2318-1.8.9/forge-1.8.9-11.15.1.2318-1.8.9-universal.jar",
    "mcp-srg.zip": "https://maven.minecraftforge.net/de/oceanlabs/mcp/mcp/1.8.9/mcp-1.8.9-srg.zip",
    "mcp-stable.zip": "https://maven.minecraftforge.net/de/oceanlabs/mcp/mcp_stable/22-1.8.9/mcp_stable-22-1.8.9.zip",
    "specialsource.jar": "https://repo.maven.apache.org/maven2/net/md-5/SpecialSource/1.11.5/SpecialSource-1.11.5-shaded.jar",
}


def run(*args):
    subprocess.run([str(a) for a in args], check=True)


def mapping_files():
    with zipfile.ZipFile(INPUTS / "mcp-stable.zip") as archive:
        names = {}
        for filename in ("fields.csv", "methods.csv"):
            names.update({row["searge"]: row["name"] for row in
                          csv.DictReader(io.StringIO(archive.read(filename).decode()))})
    with zipfile.ZipFile(INPUTS / "mcp-srg.zip") as archive:
        original = archive.read("joined.srg").decode().splitlines()
    notch_mcp, mcp_srg = [], []
    for line in original:
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "CL:":
            notch_mcp.append(line)
            mcp_srg.append(f"CL: {parts[2]} {parts[2]}")
        elif parts[0] in ("FD:", "MD:"):
            target_index = 2 if parts[0] == "FD:" else 3
            target = parts[target_index]
            owner, _, member = target.rpartition("/")
            mcp = owner + "/" + names.get(member, member)
            renamed = parts[:]
            renamed[target_index] = mcp
            notch_mcp.append(" ".join(renamed))
            if parts[0] == "FD:":
                mcp_srg.append(f"FD: {mcp} {target}")
            else:
                mcp_srg.append(f"MD: {mcp} {parts[4]} {target} {parts[4]}")
        elif parts[0] == "PK:":
            notch_mcp.append(line)
    first, second = WORK / "notch-mcp.srg", WORK / "mcp-srg.srg"
    first.write_text("\n".join(notch_mcp) + "\n")
    second.write_text("\n".join(mcp_srg) + "\n")
    return first, second


def prepare(minecraft, java):
    version = minecraft / "versions/1.8.9"
    info = json.loads((version / "1.8.9.json").read_text())
    original = version / "1.8.9.jar"
    expected = info["downloads"]["client"]["sha1"]
    with original.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha1").hexdigest() == expected, "Minecraft input hash mismatch"
    first, second = mapping_files()
    forge = WORK / "forge-mcp.jar"
    if not forge.exists():
        run(java, "-jar", INPUTS / "specialsource.jar", "--quiet", "--stable",
            "--in-jar", INPUTS / "forge-universal.jar", "--out-jar", forge, "--srg-in", first)
    source_hash = hashlib.sha256(original.read_bytes() + first.read_bytes()).hexdigest()
    mapped = WORK / "minecraft-mcp.jar"
    marker = WORK / "minecraft-mcp.sha256"
    if not mapped.is_file() or not marker.is_file() or marker.read_text() != source_hash:
        run(java, "-jar", INPUTS / "specialsource.jar", "--quiet", "--stable",
            "--in-jar", original, "--out-jar", mapped, "--srg-in", first)
        # The hierarchy is keyed by deobfuscated class names. It lets the final
        # remap resolve inherited Minecraft methods invoked on our own screens.
        run(java, "-jar", INPUTS / "specialsource.jar", "--quiet", "--stable",
            "--in-jar", mapped, "--out-jar", WORK / "minecraft-srg.jar",
            "--srg-in", second, "--write-inheritance", WORK / "inheritance.map")
        marker.write_text(source_hash)
    libraries = [p for p in (minecraft / "libraries").rglob("*.jar")
                 if any(s in str(p) for s in ("lwjgl/lwjgl/", "lwjgl/lwjgl_util/", "gson/2.2.4/",
                                              "guava/17.0/", "authlib/1.5.21/", "log4j/", "commons-lang3/3.3.2/",
                                              "asm-debug-all/5.2/", "launchwrapper/1.12/"))]
    return mapped, libraries, second


def build(minecraft, java, javac):
    import os
    mapped, libraries, remap = prepare(minecraft, java)
    classes = WORK / "classes"
    if classes.exists():
        shutil.rmtree(classes)
    classes.mkdir()
    from forge189_shared_sources import generate
    generated = WORK / "generated-java8"
    generate(ROOT, generated)
    sources = sorted((SOURCE / "java").rglob("*.java")) + sorted(generated.rglob("*.java"))
    if not sources:
        raise RuntimeError("Forge 1.8.9 client sources are missing")
    classpath = os.pathsep.join(map(str, [mapped, WORK / "forge-mcp.jar", *libraries]))
    run(javac, "--release", "8", "-proc:none", "-encoding", "UTF-8", "-classpath", classpath,
        "-d", classes, *sources)
    original = WORK / "cubeon-client-forge-dev.jar"
    with zipfile.ZipFile(original, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(classes.rglob("*.class")):
            archive.write(path, path.relative_to(classes).as_posix())
        for directory in (SOURCE / "resources", ROOT / "mod/src/main/resources/assets/cubeon-client"):
            if not directory.exists():
                continue
            for path in sorted(directory.rglob("*")):
                if path.is_file():
                    target = path.relative_to(directory).as_posix()
                    if directory.name == "cubeon-client":
                        target = "assets/cubeon-client/" + target
                    archive.write(path, target)
    destination = ROOT / "assets/jars/cubeon-client-forge-1.8.9.jar"
    destination.parent.mkdir(parents=True, exist_ok=True)
    run(java, "-jar", INPUTS / "specialsource.jar", "--quiet", "--stable",
        "--in-jar", original, "--out-jar", destination, "--srg-in", remap,
        "--read-inheritance", WORK / "inheritance.map")
    with zipfile.ZipFile(destination) as archive:
        assert "mcmod.info" in archive.namelist()
        assert not any(n.startswith("net/minecraft/") for n in archive.namelist()), "Minecraft classes in mod"
        for name in archive.namelist():
            if name.endswith(".class"):
                assert int.from_bytes(archive.read(name)[6:8], "big") <= 52, name
    print("Verified Forge 1.8.9 / Java 8 mod:", destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minecraft-dir", type=Path, default=Path.home() / ".cubeon_minecraft")
    parser.add_argument("--java", default="java")
    parser.add_argument("--javac", default="javac")
    parser.add_argument("--download-inputs", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    INPUTS.mkdir(parents=True, exist_ok=True)
    if args.download_inputs:
        for name, url in URLS.items():
            target = INPUTS / name
            if not target.is_file():
                with urllib.request.urlopen(url, timeout=30) as response:
                    target.write_bytes(response.read(32 * 1024 * 1024))
    for name in URLS:
        if not (INPUTS / name).is_file():
            raise RuntimeError(f"Missing {name}; run with --download-inputs")
    if args.prepare_only:
        prepare(args.minecraft_dir, args.java)
    else:
        build(args.minecraft_dir, args.java, args.javac)


if __name__ == "__main__":
    main()
