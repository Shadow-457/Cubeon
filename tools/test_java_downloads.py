"""Verified regional Java routes, failover/resume and atomic installation."""
import hashlib
import io
import os
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
import tarfile

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import _sandbox_home
_sandbox_home.isolate()
from cubeon import java_downloads as routes, jre, local_cache, net


def asset(provider="Eclipse Temurin", digest=None, link=None):
    return dict(provider=provider, name="java21.tar.gz", size=1000000,
                sha256=digest or "a" * 64,
                link=link or "https://github.com/adoptium/temurin21-binaries/releases/download/v/java21.tar.gz")


class JavaRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def test_rejects_unverified_sources_and_unsafe_filenames(self):
        for changed in (dict(sha256=""), dict(sha256="broken"), dict(name="../escape.tar.gz"),
                        dict(link="https://cdn.azul.com.attacker.invalid/java.tar.gz"),
                        dict(link="http://cdn.azul.com/zulu/java.tar.gz"), dict(size=0)):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                routes.validate_asset(dict(asset(), **changed))

    def test_azul_selects_a_headful_jre_with_the_correct_platform_and_hash(self):
        identity = "9a4992bb-7652-4303-8ce6-26e6849b1ead"
        row = dict(package_uuid=identity, java_version=[21, 0, 13], name="zulu21-ca-jre21-linux_x64.tar.gz")
        detail = dict(row, java_package_type="jre", os="linux", arch="x86", hw_bitness=64,
                      lib_c_type="glibc", size=123456, sha256_hash="b" * 64,
                      download_url="https://cdn.azul.com/zulu/bin/" + row["name"])
        with patch.object(net, "get_json", side_effect=[[dict(row, name="zulu21-ca-jre21-linux_musl_x64.tar.gz"), row], detail]) as api:
            result = routes._azul_asset(21, dict(os="linux", architecture="x64"))
        self.assertEqual(result["sha256"], "b" * 64)
        self.assertEqual(api.call_args_list[0].kwargs["params"]["java_package_type"], "jre")
        self.assertEqual(api.call_args_list[0].kwargs["attempts"], 1)
        for invalid in (dict(java_package_type="jdk"), dict(javafx_bundled=True),
                        dict(arch="arm"), dict(java_version=[25]), dict(sha256_hash=None)):
            with self.subTest(invalid=invalid), patch.object(net, "get_json", side_effect=[[row], dict(detail, **invalid)]), self.assertRaises(ValueError):
                routes._azul_asset(21, dict(os="linux", architecture="x64"))

    def test_route_choice_uses_measured_speed_and_vendor_hash_for_mirrors(self):
        azul = asset("Azul Zulu CDN", "b" * 64, "https://cdn.azul.com/zulu/bin/java21.tar.gz")
        with patch.object(routes, "_azul_asset", return_value=azul), \
                patch.object(local_cache, "cached_call", side_effect=lambda ns, key, fetch, **kw: fetch()), \
                patch.object(local_cache, "get", return_value=None), patch.object(local_cache, "set") as cache, \
                patch.object(routes, "_sample", side_effect=lambda a: {"Eclipse Temurin": 80, "Azul Zulu CDN": 20, "NJU mirror": 10}.get(a["provider"])):
            results = routes.candidates(21, dict(os="linux", architecture="x64"), asset)
        self.assertEqual([a["provider"] for a in results], ["NJU mirror", "Azul Zulu CDN", "Eclipse Temurin"])
        self.assertEqual(results[0]["sha256"], results[2]["sha256"])
        self.assertTrue(results[0]["link"].endswith("/21/jre/x64/linux/java21.tar.gz"))
        cache.assert_called_once()

    def test_one_vendor_can_fail_without_blocking_the_other(self):
        azul = asset("Azul Zulu CDN", "b" * 64, "https://cdn.azul.com/zulu/bin/java21.tar.gz")
        with patch.object(routes, "_azul_asset", return_value=azul), \
                patch.object(local_cache, "cached_call", side_effect=lambda ns, key, fetch, **kw: fetch()), \
                patch.object(routes, "_sample", side_effect=AssertionError("One route needs no race")):
            result = routes.candidates(21, dict(os="linux", architecture="x64"), lambda: (_ for _ in ()).throw(net.DownloadError("offline")))
        self.assertEqual(result, [azul])

    def test_successful_route_cache_skips_repeated_probes(self):
        azul = asset("Azul Zulu CDN", "b" * 64, "https://cdn.azul.com/zulu/bin/java21.tar.gz")
        with patch.object(routes, "_azul_asset", return_value=azul), \
                patch.object(local_cache, "cached_call", side_effect=lambda ns, key, fetch, **kw: fetch()), \
                patch.object(local_cache, "get", return_value=[azul["link"]]), \
                patch.object(routes, "_sample", side_effect=AssertionError("Cached route should skip samples")):
            result = routes.candidates(21, dict(os="linux", architecture="x64"), asset)
        self.assertEqual(result[0], azul)

    def test_sample_is_small_closes_the_response_and_rejects_html(self):
        class Body:
            def __init__(self, data): self.data = io.BytesIO(data); self.read = 0
            def read1(self, size, **kwargs):
                result = self.data.read(size); self.read += len(result); return result
        for blob, valid in ((b"\x1f\x8b" + b"x" * 300000, True), (b"<html>not a Java archive</html>", False)):
            body = Body(blob); closed = []
            response = types.SimpleNamespace(status_code=200, headers={}, raw=body,
                                             close=lambda: closed.append(True))
            with patch.object(net, "get_with_retry", return_value=response) as get:
                score = routes._sample(asset())
            self.assertEqual(score is not None, valid)
            self.assertLessEqual(body.read, routes.SAMPLE_BYTES)
            self.assertEqual(closed, [True])
            self.assertEqual(get.call_args.kwargs["attempts"], 1)
            self.assertEqual(get.call_args.kwargs["headers"]["Range"], "bytes=0-131071")

    def test_partial_bytes_resume_on_matching_mirror_but_never_another_vendor(self):
        first = asset()
        mirror = dict(first, provider="NJU mirror", link="https://mirrors.nju.edu.cn/adoptium/java21.tar.gz")
        other = asset("Azul Zulu CDN", "b" * 64, "https://cdn.azul.com/zulu/bin/java21.tar.gz")
        seen = []
        def transfer(path, url, **kwargs):
            partial = Path(path + ".part")
            seen.append(partial.read_bytes() if partial.exists() else b"")
            self.assertEqual(kwargs["attempts"], 1)
            self.assertTrue(kwargs["url_validator"](url))
            if len(seen) == 1:
                partial.write_bytes(b"verified-vendor-prefix")
                raise net.DownloadError("connection dropped")
            if len(seen) == 2:
                raise net.DownloadError("mirror unavailable")
            Path(path).write_bytes(b"finished")
        with patch.object(net, "download_to", side_effect=transfer):
            routes.download([first, mirror, other], str(self.directory), 21)
        self.assertEqual(seen, [b"", b"verified-vendor-prefix", b""])

    def test_failed_download_keeps_partial_for_a_later_retry(self):
        def fail(path, url, **kwargs):
            Path(path + ".part").write_bytes(b"prefix")
            raise net.DownloadError("temporarily offline")
        with patch.object(net, "download_to", side_effect=fail), self.assertRaisesRegex(RuntimeError, "Partial downloads are kept"):
            routes.download([asset()], str(self.directory), 21)
        self.assertEqual(next(self.directory.glob("*.part")).read_bytes(), b"prefix")

    def test_user_cancellation_is_not_treated_as_a_route_failure(self):
        def transfer(path, url, **kwargs): kwargs["progress_cb"](1, 100)
        def cancel(done, total): raise InterruptedError("cancelled")
        with patch.object(net, "download_to", side_effect=transfer) as download, self.assertRaises(InterruptedError):
            routes.download([asset(), asset("Azul Zulu CDN")], str(self.directory), 21, progress_cb=cancel)
        self.assertEqual(download.call_count, 1)

    def test_slow_source_switches_without_switching_after_completion(self):
        clock = [0]
        def transfer(path, url, **kwargs):
            clock[0] += 13
            kwargs["progress_cb"](1000 if "github" in url else 1000000, 1000000)
            Path(path).write_bytes(b"finished")
        second = asset("Azul Zulu CDN", "b" * 64, "https://cdn.azul.com/zulu/bin/java21.tar.gz")
        with patch.object(routes.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(net, "download_to", side_effect=transfer) as download:
            result = routes.download([asset(), second], str(self.directory), 21)
        self.assertIn("b" * 64, result)
        self.assertEqual(download.call_count, 2)

    def test_mac_archive_home_is_promoted_correctly(self):
        archive = self.directory / "mac.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            info = tarfile.TarInfo("jdk21/Contents/Home/bin/java"); info.size = 4
            tar.addfile(info, io.BytesIO(b"java"))
        with patch.object(jre, "_java_binary", return_value="java"):
            self.assertEqual(jre._extract(str(archive), str(self.directory / "out")), "jdk21/Contents/Home")

    @unittest.skipIf(os.name == "nt", "POSIX executable fixture")
    def test_actual_install_coalesces_and_runs_both_probes_before_success(self):
        archive = self.directory / "runtime.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            script = b'#!/bin/sh\necho \'openjdk version "21.0.13"\' >&2\n'
            info = tarfile.TarInfo("zulu21/bin/java"); info.size = len(script); info.mode = 0o755
            tar.addfile(info, io.BytesIO(script))
        results = []
        with patch.object(jre, "RUNTIMES_DIR", str(self.directory / "runtimes")), \
                patch.object(routes, "candidates", return_value=[asset()]) as discover, \
                patch.object(routes, "download", return_value=str(archive)) as download:
            threads = [threading.Thread(target=lambda: results.append(jre.install_jre(21))) for _ in range(2)]
            for thread in threads: thread.start()
            for thread in threads: thread.join(timeout=10)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], results[1])
        self.assertTrue(Path(results[0]).is_file())
        discover.assert_called_once(); download.assert_called_once()


if __name__ == "__main__":
    unittest.main()
