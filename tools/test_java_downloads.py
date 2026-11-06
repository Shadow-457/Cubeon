"""Verified regional Java routes, failover/resume and atomic installation."""
import hashlib
import io
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch
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
        self.assertEqual([a["provider"] for a in results], ["NJU mirror", "Azul Zulu CDN", "Eclipse Temurin", "Tsinghua mirror"])
        self.assertEqual(results[0]["sha256"], results[2]["sha256"])
        self.assertTrue(results[0]["link"].endswith("/21/jre/x64/linux/java21.tar.gz"))
        cache.assert_called_once()

    def test_failed_samples_keep_vendor_and_mirror_fallbacks(self):
        azul = asset("Azul Zulu CDN", "b" * 64, "https://cdn.azul.com/zulu/bin/java21.tar.gz")
        with patch.object(routes, "_azul_asset", return_value=azul), \
                patch.object(local_cache, "cached_call", side_effect=lambda ns, key, fetch, **kw: fetch()), \
                patch.object(local_cache, "get", return_value=None), patch.object(local_cache, "set"), \
                patch.object(routes, "_sample", return_value=None):
            results = routes.candidates(21, dict(os="linux", architecture="x64"), asset)
        self.assertEqual(len(results), 4)
        self.assertIn(azul, results)
        self.assertTrue(any(a["provider"] == "NJU mirror" for a in results))

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

    def test_retry_resumes_preferred_source_and_caches_the_completed_route(self):
        first = asset()
        second = asset("Azul Zulu CDN", "b" * 64, "https://cdn.azul.com/zulu/bin/java21.tar.gz")
        seen = []
        def transfer(path, url, **kwargs):
            seen.append(url)
            if len(seen) < 3:
                Path(path + ".part").write_bytes(b"prefix")
                raise net.DownloadError("temporary failure")
            self.assertEqual(Path(path + ".part").read_bytes(), b"prefix")
            Path(path).write_bytes(b"finished")
        with patch.object(net, "download_to", side_effect=transfer), patch.object(local_cache, "set") as cache:
            routes.download([first, second], str(self.directory), 21)
        self.assertEqual(seen, [first["link"], second["link"], first["link"]])
        self.assertEqual(cache.call_args.args[2][0], first["link"])

    def test_retry_uses_actual_transfer_speed_when_a_sample_was_misleading(self):
        first = asset()
        second = asset("Azul Zulu CDN", "b" * 64, "https://cdn.azul.com/zulu/bin/java21.tar.gz")
        seen = []
        clock = [0]
        def transfer(path, url, **kwargs):
            seen.append(url)
            clock[0] += 3
            if len(seen) < 3:
                done = 90000 if url == first["link"] else 500000
                Path(path + ".part").write_bytes(b"prefix")
                kwargs["progress_cb"](done, 1000000)
                raise net.DownloadError("temporarily disconnected")
            Path(path).write_bytes(b"finished")
        with patch.object(net, "download_to", side_effect=transfer), \
                patch.object(routes.time, "monotonic", side_effect=lambda: clock[0]):
            routes.download([first, second], str(self.directory), 21)
        self.assertEqual(seen, [first["link"], second["link"], second["link"]])

    def test_sample_estimate_does_not_repeat_connection_latency_per_chunk(self):
        body = io.BytesIO(b"\x1f\x8b" + b"x" * (routes.SAMPLE_BYTES - 2))
        response = types.SimpleNamespace(status_code=200, headers={},
                                         raw=types.SimpleNamespace(read1=lambda size, **kw: body.read(size)),
                                         close=lambda: None)
        clock = [0]
        def now():
            # A two-second connection followed by a fast transfer.
            clock[0] += 1
            return 0 if clock[0] == 1 else 2 if clock[0] < 19 else 2.05
        with patch.object(net, "get_with_retry", return_value=response), patch.object(routes.time, "monotonic", side_effect=now):
            score = routes._sample(asset())
        self.assertLess(score, 3)

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
                patch.object(routes, "_download_ranges", side_effect=routes.RangeUnsupported("serial source")), \
                patch.object(net, "download_to", side_effect=transfer) as download:
            result = routes.download([asset(), second], str(self.directory), 21)
        self.assertIn("b" * 64, result)
        self.assertEqual(download.call_count, 2)

    def test_minute_long_trickle_switches_to_an_available_alternative(self):
        clock = [0]
        first = dict(asset(), size=60 * 1024 * 1024)
        second = dict(asset("Azul Zulu CDN", "b" * 64, "https://cdn.azul.com/zulu/bin/java21.tar.gz"), size=first["size"])
        def transfer(path, url, **kwargs):
            clock[0] += 13
            kwargs["progress_cb"](100 * 1024 * 13 if "github" in url else second["size"], first["size"])
            Path(path).write_bytes(b"finished")
        with patch.object(routes.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(routes, "_download_ranges", side_effect=routes.RangeUnsupported("serial source")), \
                patch.object(net, "download_to", side_effect=transfer) as download:
            result = routes.download([first, second], str(self.directory), 21)
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


class ParallelJavaDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.payload = b"\x1f\x8b" + b"runtime" * ((routes.RANGE_MIN_BYTES + 23) // 7)
        self.asset = dict(asset(), size=len(self.payload), sha256=hashlib.sha256(self.payload).hexdigest())
        self.archive = str(self.directory / "runtime.tar.gz")
        self.requests = []
        self.active = self.peak = 0
        self.lock = threading.Lock()
        self.responses = []
        self.fail_once = False

    def get(self, url, **kwargs):
        self.assertTrue(kwargs["url_validator"](url))
        self.assertEqual(kwargs["headers"]["Accept-Encoding"], "identity")
        begin, end = map(int, kwargs["headers"]["Range"].removeprefix("bytes=").split("-"))
        self.assertGreaterEqual(begin, 0)
        self.assertLess(end, len(self.payload))
        self.assertLessEqual(end - begin + 1, routes.RANGE_CHUNK_BYTES)
        with self.lock:
            self.requests.append((url, begin, end))
            self.active += 1
            self.peak = max(self.peak, self.active)
        source = io.BytesIO(self.payload[begin:end + 1])
        closed = False
        reads = 0
        owner = self
        class Body:
            def read1(self, size, **kw):
                nonlocal reads
                reads += 1
                if reads == 1:
                    time.sleep(.005)  # overlap the simulated network reads
                if owner.fail_once and begin == 0 and reads == 2:
                    owner.fail_once = False
                    from urllib3.exceptions import HTTPError
                    raise HTTPError("connection dropped")
                return source.read(size)
        def close():
            nonlocal closed
            if not closed:
                closed = True
                with self.lock:
                    self.active -= 1
        response = types.SimpleNamespace(status_code=206, raw=Body(), close=close,
                                         headers={"Content-Range": f"bytes {begin}-{end}/{len(self.payload)}"})
        self.responses.append(response)
        return response

    def download(self, source=None, progress=None):
        with patch.object(net, "get_with_retry", side_effect=self.get):
            return routes._download_ranges(self.archive, source or self.asset, progress, time.monotonic() + 10)

    def test_parallel_ranges_obey_the_connection_cap_and_verify_the_whole_archive(self):
        counts = []
        size = self.download(progress=lambda done, total: counts.append(done))
        self.assertEqual(size, len(self.payload))
        self.assertEqual(Path(self.archive).read_bytes(), self.payload)
        self.assertGreater(self.peak, 1)
        self.assertLessEqual(self.peak, net.MAX_CONCURRENT_DOWNLOADS)
        self.assertEqual(self.active, 0)
        self.assertEqual(counts, sorted(counts))
        self.assertEqual(counts[-1], size)
        self.assertFalse(Path(self.archive + ".parts").exists())

    def test_serial_partial_prefix_is_preserved_when_switching_to_parallel_ranges(self):
        prefix = 121337
        Path(self.archive + ".part").write_bytes(self.payload[:prefix])
        self.download()
        self.assertEqual(Path(self.archive).read_bytes(), self.payload)
        self.assertTrue(all(begin >= prefix for _, begin, _ in self.requests))

    def test_dropped_chunks_resume_at_their_absolute_offsets_on_a_matching_mirror(self):
        self.fail_once = True
        with self.assertRaises(net.DownloadError):
            self.download()
        self.assertFalse(Path(self.archive).exists())
        retained = list(Path(self.archive + ".parts").iterdir())
        self.assertTrue(any(0 < part.stat().st_size < routes.RANGE_CHUNK_BYTES for part in retained))
        mirror = dict(self.asset, link="https://mirrors.nju.edu.cn/adoptium/runtime.tar.gz", provider="NJU mirror")
        self.requests.clear()
        self.download(mirror)
        self.assertTrue(any(begin % routes.RANGE_CHUNK_BYTES != 0 for _, begin, _ in self.requests))
        self.assertEqual(Path(self.archive).read_bytes(), self.payload)
        self.assertEqual(self.active, 0)

    def test_ignored_range_closes_the_probe_and_uses_one_serial_download(self):
        response = types.SimpleNamespace(status_code=200, headers={}, close=lambda: closed.append(True))
        closed = []
        def serial(path, url, **kwargs):
            self.assertEqual(kwargs["expected_hash"], ("sha256", self.asset["sha256"]))
            Path(path).write_bytes(self.payload)
        with patch.object(net, "get_with_retry", return_value=response) as get, \
                patch.object(net, "download_to", side_effect=serial) as download:
            result = routes.download([self.asset], str(self.directory), 21)
        self.assertEqual(get.call_count, 1)
        self.assertEqual(download.call_count, 1)
        self.assertEqual(closed, [True])
        self.assertEqual(Path(result).read_bytes(), self.payload)

    def test_cancellation_closes_all_responses_and_releases_download_slots(self):
        def cancel(done, total):
            if done:
                raise InterruptedError("cancelled")
        with self.assertRaises(InterruptedError):
            self.download(progress=cancel)
        self.assertEqual(self.active, 0)
        self.assertFalse(Path(self.archive).exists())
        acquired = []
        try:
            for _ in range(net.MAX_CONCURRENT_DOWNLOADS):
                acquired.append(net.DOWNLOAD_GATE.acquire(blocking=False))
            self.assertTrue(all(acquired))
        finally:
            for locked in acquired:
                if locked:
                    net.DOWNLOAD_GATE.release()

    def test_cancellation_while_queued_never_opens_a_connection(self):
        for _ in range(net.MAX_CONCURRENT_DOWNLOADS):
            net.DOWNLOAD_GATE.acquire()
        checks = 0
        def cancel():
            nonlocal checks
            checks += 1
            if checks > 1:
                raise InterruptedError("cancelled while queued")
        try:
            with patch.object(net, "get_with_retry") as get, self.assertRaises(InterruptedError):
                routes._download_ranges(self.archive, self.asset, None, time.monotonic() + 10, cancel)
            get.assert_not_called()
            checks = 0
            with patch.object(net, "get_with_retry") as get, self.assertRaises(InterruptedError):
                net.download_to(self.archive, self.asset["link"], cancel_check=cancel)
            get.assert_not_called()
        finally:
            for _ in range(net.MAX_CONCURRENT_DOWNLOADS):
                net.DOWNLOAD_GATE.release()

    def test_bad_ranges_and_bad_checksums_cannot_publish_an_archive(self):
        response = types.SimpleNamespace(status_code=206, headers={"Content-Range": "bytes 0-0/1"}, close=Mock())
        with patch.object(net, "get_with_retry", return_value=response), self.assertRaises(routes.RangeUnsupported):
            routes._download_ranges(self.archive, self.asset, None, time.monotonic() + 10)
        response.close.assert_called_once()
        with self.assertRaisesRegex(net.DownloadError, "integrity"):
            self.download(dict(self.asset, sha256="a" * 64))
        self.assertFalse(Path(self.archive).exists())
        self.assertFalse(Path(self.archive + ".part").exists())
        self.assertFalse(Path(self.archive + ".parts").exists())


if __name__ == "__main__":
    unittest.main()
