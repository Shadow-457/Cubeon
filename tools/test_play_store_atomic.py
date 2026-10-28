"""The play-store read-modify-write is serialized and ignores booleans (7.4).

`instances.mark_played` read the whole JSON, edited and wrote a fixed
`instance_play.json.tmp`. Two launches at once used the same temp file: one
replace consumed it and the other raised `FileNotFoundError` (swallowed), so
one instance's "last played" vanished. `_read_play_store` also accepted
`true` as a timestamp because `bool` is an `int`.

The race is made deterministic: `os.replace` is held inside the first writer
until the second one has had its chance. Pre-fix the second writer reads the
old file, replaces the shared temp path, and the first update is lost.

Run: python tools/test_play_store_atomic.py
"""
import json
import os
import sys
import tempfile
import threading
from unittest.mock import patch

sys.path[:0] = [os.path.dirname(__file__),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
import _sandbox_home

_sandbox_home.isolate()

from cubeon import instances  # noqa: E402

passed = failed = 0


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


def main():
    scratch = tempfile.mkdtemp(prefix="cubeon-play-store-")
    store_path = os.path.join(scratch, "instance_play.json")
    instances._PLAY_STORE = store_path

    # --- booleans are not timestamps ---------------------------------------
    with open(store_path, "w", encoding="utf-8") as fh:
        json.dump({"alpha": True, "beta": 123.0, "gamma": 1}, fh)
    store = instances.play_store()
    check("a boolean entry is ignored", "alpha" not in store, str(store))
    check("real numbers still load",
          store == {"beta": 123.0, "gamma": 1.0}, str(store))

    # --- concurrent writers do not lose an entry ---------------------------
    os.unlink(store_path)
    real_replace = os.replace
    first_in_replace = threading.Event()
    release_first = threading.Event()
    b_done = threading.Event()
    calls = {"n": 0}
    calls_lock = threading.Lock()

    def slow_replace(src, dst):
        with calls_lock:
            calls["n"] += 1
            n = calls["n"]
        if n == 1:
            first_in_replace.set()
            release_first.wait(10)
        return real_replace(src, dst)

    def mark(vid, when):
        instances.mark_played(vid, when)

    def mark_b():
        try:
            mark("B", 2.0)
        finally:
            b_done.set()

    with patch.object(instances.os, "replace", slow_replace):
        a = threading.Thread(target=mark, args=("A", 1.0))
        a.start()
        check("the first writer reached os.replace",
              first_in_replace.wait(5))
        b = threading.Thread(target=mark_b)
        b.start()
        # Pre-fix B reads the old store and finishes while A is frozen.
        # Post-fix B is blocked on the play-store lock.
        b_finished_early = b_done.wait(0.5)
        release_first.set()
        a.join(10)
        b.join(10)

    check("the second writer waited for the first",
          not b_finished_early,
          "both writers ran their read-modify-write at the same time")
    final = instances.play_store()
    check("both launches are recorded",
          set(final) == {"A", "B"}, str(final))
    leftovers = [n for n in os.listdir(scratch) if n.endswith(".tmp")]
    check("no temp file is left behind", not leftovers, str(leftovers))

    print()
    print(f"{passed} passed, {failed} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
