"""Exercise release manifests, generation fallback and draft verification offline."""
import bz2
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))
import _sandbox_home
_sandbox_home.isolate()
from cubeon import auto_update as update

spec = importlib.util.spec_from_file_location("cubeon_build_updates", ROOT / "packaging/build_updates.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def number(value):
    return (abs(value) | (1 << 63 if value < 0 else 0)).to_bytes(8, "little")


def diff(old, new, destination):
    count = min(len(old), len(new))
    control = bz2.compress(number(count) + number(len(new) - count) + number(0))
    delta = bz2.compress(bytes((new[n] - old[n]) & 255 for n in range(count)))
    Path(destination).write_bytes(b"BSDIFF40" + number(len(control)) + number(len(delta))
                                 + number(len(new)) + control + delta + bz2.compress(new[count:]))


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        header = bytearray(64)
        header[:6], header[8:11], header[18:20] = b"\x7fELF\x02\x01", b"AI\x02", b"\x3e\x00"
        self.base = self.root / "base"
        self.target = self.root / "target"
        self.base.write_bytes(bytes(header) + b"old code" * 4096)
        self.target.write_bytes(bytes(header) + b"new code" * 4096)
        windows = bytearray(128)
        windows[:2], windows[60:64], windows[64:70] = b"MZ", number(64)[:4], b"PE\0\0\x4c\x01"
        self.windows = self.root / "windows"
        self.windows.write_bytes(bytes(windows) + b"Windows code" * 4096)
        self.output = self.root / "assets"
        module = types.SimpleNamespace(file_diff=lambda base, new, patch:
                                       diff(Path(base).read_bytes(), Path(new).read_bytes(), patch))
        self.mock_module = module
        stack = self.enterContext(__import__("contextlib").ExitStack())
        stack.enter_context(mock.patch.dict(sys.modules, bsdiff4=module))
        stack.enter_context(mock.patch.object(builder.importlib.metadata, "version", return_value="1.4.4"))

    def generate(self, bases=None):
        return builder.generate("linux", "1.5.0", self.target, self.output,
                                bases if bases is not None else [("1.4.9", self.base)])

    def metadata(self, manifest):
        paths = {update.ASSETS["linux"]: self.target}
        if (self.output / update.MANIFESTS["windows"]).exists():
            paths[update.ASSETS["windows"]] = self.windows
        paths.update({p.name: p for p in self.output.iterdir() if p.suffix in (".bsdiff", ".json")
                      and not p.name.endswith("measurements.json")})
        assets = [{"name": name, "state": "uploaded", "size": path.stat().st_size,
                   "digest": "sha256:" + update.file_hash(path),
                   "browser_download_url": f"https://github.com/{update.REPOSITORY}/releases/download/v1.5.0/{name}"}
                  for name, path in paths.items()]
        return {"tag_name": "v1.5.0", "draft": True, "prerelease": False, "assets": assets}, paths

    def test_generated_manifest_reconstructs_and_is_pinned_to_release_assets(self):
        manifest = self.generate()
        self.assertEqual(len(manifest["patches"]), 1)
        data, paths = self.metadata(manifest)
        release = update.parse_release(dict(data, draft=False), "linux", "0.0.0")
        refs = update.parse_manifest(manifest, release, "linux")
        self.assertEqual(refs[0][1:], (self.base.stat().st_size, update.file_hash(self.base)))
        builder.generate("windows", "1.5.0", self.windows, self.output, [])
        data, paths = self.metadata(manifest)
        def download(tag, asset, cache):
            path = paths[asset.name]
            update._verify_asset(path, asset, threading.Event())
            return path
        with mock.patch.object(builder, "release_metadata", return_value=data), \
                mock.patch.object(builder, "download_staged", side_effect=download) as get:
            builder.verify_published_assets("v1.5.0", self.root)
        self.assertEqual(get.call_count, 3)  # both manifests and the Linux patch

    def test_publication_rejects_missing_platform_manifest_and_patch_reference(self):
        manifest = self.generate()
        data, _ = self.metadata(manifest)
        with mock.patch.object(builder, "release_metadata", return_value=data), \
                mock.patch.object(builder, "download_staged", return_value=self.output / update.MANIFESTS["linux"]):
            with self.assertRaises(update.UpdateError):
                builder.verify_published_assets("v1.5.0", self.root)
        data["assets"] = [a for a in data["assets"] if not a["name"].endswith(".bsdiff")]
        release = update.parse_release(dict(data, draft=False), "linux", "0.0.0")
        with self.assertRaises(update.UpdateError):
            update.parse_manifest(manifest, release, "linux")

    def test_empty_manifest_and_bad_or_large_patch_use_full_artifact(self):
        self.assertEqual(self.generate([])["patches"], [])
        for payload in (b"invalid", b"x" * self.target.stat().st_size):
            self.mock_module.file_diff = lambda base, new, patch: Path(patch).write_bytes(payload)
            self.assertEqual(self.generate()["patches"], [])
            self.assertFalse(list(self.output.glob("*.bsdiff")))

    def test_duplicate_or_future_bases_are_rejected(self):
        for bases in ([("1.5.0", self.base)], [("1.4.9", self.base)] * 2):
            with self.assertRaises(ValueError):
                self.generate(bases)

    def test_draft_lookup_uses_resolved_api_id(self):
        url = f"https://api.github.com/repos/{update.REPOSITORY}/releases/123"
        with mock.patch.object(builder, "gh_json", side_effect=[{"apiUrl": url}, {"draft": True}]) as gh:
            self.assertEqual(builder.release_metadata("v1.5.0"), {"draft": True})
        self.assertEqual(gh.call_args_list[1].args, ("api", url))

    def test_authenticated_staged_download_checks_the_github_digest(self):
        body = b"manifest payload" * 64
        asset = update.Asset("Cubeon-Linux-x64-update.json", "unused draft URL", len(body),
                             hashlib.sha256(body).hexdigest())
        def download(command, **kwargs):
            (self.root / asset.name).write_bytes(body)
        with mock.patch.object(builder.subprocess, "run", side_effect=download) as run:
            self.assertEqual(builder.download_staged("v1.5.0", asset, self.root).read_bytes(), body)
        self.assertEqual(run.call_args.args[0][:4], ["gh", "release", "download", "v1.5.0"])
        with mock.patch.object(builder.subprocess, "run", side_effect=download), self.assertRaises(update.UpdateError):
            builder.download_staged("v1.5.0", update.Asset(asset.name, asset.url, len(body), "a" * 64), self.root)

    def test_manifest_resource_limits_and_exact_digests(self):
        manifest = self.generate()
        data, _ = self.metadata(manifest)
        release = update.parse_release(dict(data, draft=False), "linux", "0.0.0")
        for changes in ({"schema": True}, {"patches": manifest["patches"] * 4}):
            with self.assertRaises(update.UpdateError):
                update.parse_manifest(dict(manifest, **changes), release, "linux")
        for field, value in (("base_size", update.MAX_ASSET + 1), ("base_sha256", "invalid"),
                             ("sha256", "a" * 64), ("size", True)):
            invalid = copy.deepcopy(manifest)
            invalid["patches"][0][field] = value
            with self.assertRaises(update.UpdateError):
                update.parse_manifest(invalid, release, "linux")


if __name__ == "__main__":
    unittest.main()
