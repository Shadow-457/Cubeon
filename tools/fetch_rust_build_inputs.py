#!/usr/bin/env python3
"""Download official, pinned Minecraft inputs locally for exporter builds.

These files stay in ignored build/ and are never release artifacts.
"""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cubeon import net


def main():
    import minecraft_launcher_lib as mll
    game = ROOT / "build/rust-inputs"
    lock = json.loads((ROOT / "native/cubeon-rust/research-lock.json").read_text())["minecraft"]
    version = lock["version"]
    mll.install.install_minecraft_version(version, str(game), callback={"setStatus": print})
    manifest = game / f"versions/{version}/{version}.json"
    with manifest.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha1").hexdigest()
    if digest not in {lock["manifest_sha1"], *lock["accepted_manifest_sha1"]}:
        raise RuntimeError("Mojang manifest changed; review and update the source pin before building")
    info = json.loads(manifest.read_text())
    server = info["downloads"]["server"]
    if server["sha1"] != lock["server_sha1"]:
        raise RuntimeError("Server resource input differs from Cubeon's source pin")
    from cubeon.rust_engine import _official_url
    if not _official_url(server["url"]):
        raise RuntimeError("Server resource input is not hosted by Mojang")
    net.download_to(str(game / "server.jar"), server["url"],
                    expected_hash=("sha1", lock["server_sha1"]), url_validator=_official_url)


if __name__ == "__main__":
    main()
