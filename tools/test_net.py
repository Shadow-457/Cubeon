"""Tests for cubeon/net.py (retry, resume, concurrency gate) and
cubeon/updater.py (version comparison, feed parsing). Fully hermetic:
requests.get is faked, no network."""
import hashlib
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cubeon import net, updater  # noqa: E402

_passed = 0
_failed = 0


def check(cond, msg):
    global _passed, _failed
    if cond:
        _passed += 1
    else:
        _failed += 1
        print(f"  FAIL: {msg}")


class FakeResp:
    def __init__(self, chunks, status=200, headers=None, error_after=None,
                 json_body=None):
        self._chunks = chunks
        self.status_code = status
        self.headers = headers or {}
        self._error_after = error_after  # die after N chunks: simulates a drop
        self.closed = False
        self._json = json_body

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=1 << 16):
        sent = 0
        for c in self._chunks:
            if self._error_after is not None and sent >= self._error_after:
                import requests
                raise requests.ConnectionError("connection reset by peer")
            sent += 1
            yield c

    def close(self):
        self.closed = True


def fake_get_factory(responses):
    """Pop responses in order; a RequestException entry simulates a failure."""
    import requests
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        item = responses.pop(0) if responses else None
        if isinstance(item, Exception):
            raise item
        return item

    fake_get.calls = calls
    return fake_get


def with_monkeypatched_get(fn):
    def run():
        real = net.requests.get
        try:
            fn()
        finally:
            net.requests.get = real
    return run


def tmpdir():
    import tempfile
    return tempfile.mkdtemp(prefix="cubeon-net-test-")


# ---------------------------------------------------------------- updater ---
check(updater.is_newer("v1.1.0", "1.0.0"), "v-prefixed tag parses")
check(updater.is_newer("1.0.1", "1.0.0"), "plain tag parses")
check(not updater.is_newer("1.0.0", "1.0.0"), "same version is not newer")
check(not updater.is_newer("0.9.9", "1.0.0"), "older tag is not newer")
check(not updater.is_newer("weird-tag", "1.0.0"),
      "unparseable tag compares as not-newer (never nag on ambiguity)")


@with_monkeypatched_get
def _updater_feed():
    net.requests.get = lambda *a, **k: FakeResp(
        [], json_body={"tag_name": "v9.9.9", "html_url": "https://x/release",
                       "body": "notes here"})
    info = updater.check_for_updates(feed_url="https://feed")
    check(info == {"version": "9.9.9", "url": "https://x/release",
                   "notes": "notes here"}, "newer release is reported")

    net.requests.get = lambda *a, **k: FakeResp(
        [], json_body={"tag_name": "v1.0.0"})
    check(updater.check_for_updates(feed_url="https://feed") is None,
          "up-to-date feed yields None")


_updater_feed()


# -------------------------------------------------------------------- net ---
@with_monkeypatched_get
def _happy_path():
    d = tmpdir()
    dest = os.path.join(d, "file.jar")
    fake = FakeResp([b"hello ", b"world"])
    net.requests.get = lambda *a, **k: fake
    got = net.download_to(dest, "https://cdn/x", attempts=1)
    check(got == 11 and open(dest, "rb").read() == b"hello world",
          "simple download lands complete")
    check(fake.closed, "response is closed after use")
    check(not os.path.exists(dest + ".part"), "no .part litter on success")


_happy_path()


@with_monkeypatched_get
def _retry_on_503():
    d = tmpdir()
    dest = os.path.join(d, "f")
    net.requests.get = fake_get_factory([FakeResp([], status=503),
                                         FakeResp([b"ok"])])
    net.BACKOFF_BASE = 0.01  # don't sleep the test suite
    try:
        got = net.download_to(dest, "https://cdn/x", attempts=3)
    finally:
        net.BACKOFF_BASE = 1.5
    check(got == 2 and open(dest, "rb").read() == b"ok",
          "5xx is retried and succeeds")


_retry_on_503()


@with_monkeypatched_get
def _no_retry_on_404():
    d = tmpdir()
    dest = os.path.join(d, "f")
    fake = fake_get_factory([FakeResp([], status=404), FakeResp([b"nope"])])
    net.requests.get = fake
    try:
        net.download_to(dest, "https://cdn/x", attempts=3)
        check(False, "404 must raise")
    except net.DownloadError:
        check(len(fake.calls) == 1, "404 is NOT retried (it can never succeed)")


@with_monkeypatched_get
def _resume():
    d = tmpdir()
    dest = os.path.join(d, "big.jar")
    body = b"A" * 1000 + b"B" * 500
    remaining = b"B" * 500

    # 1) server honors Range -> 206, append: stitches prefix + tail
    with open(dest + ".part", "wb") as fh:
        fh.write(b"A" * 1000)
    net.requests.get = lambda *a, **k: FakeResp([remaining], status=206)
    net.download_to(dest, "https://cdn/big", attempts=1)
    check(open(dest, "rb").read() == body,
          "resumed download stitches the prefix + tail")

    # 2) server ignores Range -> 200 full body: clean restart, no dupe
    with open(dest + ".part", "wb") as fh:
        fh.write(b"A" * 1000)
    net.requests.get = lambda *a, **k: FakeResp([remaining])
    net.download_to(dest, "https://cdn/big", attempts=1)
    check(open(dest, "rb").read() == remaining,
          "Range-ignoring server triggers a clean restart (no stitched dupe)")


_resume()


@with_monkeypatched_get
def _hash_mismatch():
    d = tmpdir()
    dest = os.path.join(d, "f")
    net.requests.get = lambda *a, **k: FakeResp([b"corrupted!"])
    h = hashlib.sha256(b"expected").hexdigest()
    try:
        net.download_to(dest, "https://cdn/f", attempts=1,
                        expected_hash=("sha256", h))
        check(False, "hash mismatch must raise")
    except net.DownloadError:
        check(True, "hash mismatch raises DownloadError")
    check(not os.path.exists(dest + ".part"),
          "mismatched partial is cleaned up, not kept")
    check(not os.path.exists(dest), "dest untouched on hash mismatch")


_hash_mismatch()


@with_monkeypatched_get
def _midbody_drop_retries():
    import requests
    d = tmpdir()
    dest = os.path.join(d, "f")
    # Attempt 1 dies mid-body after one chunk; the partial survives and
    # attempt 2 resumes from it and completes.
    net.requests.get = fake_get_factory([
        FakeResp([b"part1", b"part2"], error_after=1),
        FakeResp([b"rest"], status=206),
    ])
    net.BACKOFF_BASE = 0.01
    try:
        net.download_to(dest, "https://cdn/f", attempts=3)
        check(open(dest, "rb").read() == b"part1rest",
              "mid-body drop resumes from the partial file")
    finally:
        net.BACKOFF_BASE = 1.5


_midbody_drop_retries()


@with_monkeypatched_get
def _concurrency_cap():
    d = tmpdir()
    state = {"active": 0, "peak": 0}
    lock = threading.Lock()

    def slow_get(url, **kwargs):
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        time.sleep(0.15)
        with lock:
            state["active"] -= 1
        return FakeResp([b"x"])

    net.requests.get = slow_get
    threads = [threading.Thread(
        target=lambda i=i: net.download_to(os.path.join(d, f"f{i}"),
                                           f"https://cdn/{i}", attempts=1))
        for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check(state["peak"] <= net.MAX_CONCURRENT_DOWNLOADS,
          f"concurrent downloads capped (peak was {state['peak']})")
    check(all(os.path.isfile(os.path.join(d, f"f{i}")) for i in range(8)),
          "all capped downloads still complete")


_concurrency_cap()

print(f"{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)

