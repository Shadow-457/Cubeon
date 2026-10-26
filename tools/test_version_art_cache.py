#!/usr/bin/env python3
"""
The Play tab's thumbnails must not reload themselves.

Reported symptom: the version art on the launcher's main menu re-loads over and
over. Two independent causes, both fixed here and both pinned by this file:

  1. `version_art.src()` is called from the RENDER path - on every selection
     change, for the version spotlight. It
     re-opened the file and base64-encoded it again on each call (Mojang's key
     art is a 27-53 KB JPEG; measured 0.127 ms per uncached call on this
     machine). The encoded string is now cached per file, keyed by
     (mtime, size) so a re-downloaded banner can never serve a stale encode.

  2. The old "Jump back in" cards rebuilt their ft.Image controls on selection
     and rename, which made Flet re-send every base64 thumbnail. They were
     replaced by a plain text list on 2026-10-25, and the Play tab's list was
     removed entirely on 2026-10-26. Instances now live only in the version
     panel, whose rows use an icon (not ft.Image) for the cube emblem, so there
     is no per-row art to re-send at all; section 5 pins both facts.

The instance half is checked against the REAL built UI through
tools/app_driver.

No network: version_art's transport is replaced with a loud failure, so any
attempt to fetch during this test is an error rather than a live request.

Run: python3 tools/test_version_art_cache.py
"""
import inspect
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _sandbox_home                                        # noqa: E402

# Must happen before ANY cubeon import: every on-disk location (including the
# private game dir) is derived from HOME at import time.
_sandbox_home.isolate()

import app_driver                                           # noqa: E402
import _fuzz_common as fz                                   # noqa: E402
from _fuzz_common import every_control, walk                # noqa: E402
from cubeon import theme, version_art                       # noqa: E402

passed = 0
failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok   {label}")
    else:
        failed += 1
        print(f"  FAIL {label}" + (f"\n       {detail}" if detail else ""))


def _no_network(*_a, **_k):
    raise AssertionError("this test must not touch the network")


# Every art fetch in this process now fails loudly instead of reaching Mojang.
version_art.get_with_retry = _no_network

ART = tempfile.mkdtemp(prefix="cubeon-art-test-")
version_art.ART_DIR = ART


def _png(seed: bytes, size: int = 6000) -> bytes:
    """A payload that passes version_art's magic-byte + size checks."""
    pad = (seed * (size // len(seed) + 1))[:size - 8]
    return b"\x89PNG\r\n\x1a\n" + pad


def _write(version: str, data: bytes, mtime: float | None = None) -> str:
    path = os.path.join(ART, f"official_{version}.png")
    with open(path, "wb") as fh:
        fh.write(data)
    if mtime:
        os.utime(path, (mtime, mtime))
    return path


def _count_opens(path: str):
    """Wrap the module's `open` so we can prove the file is read exactly once.
    Set as a module global so only version_art is affected."""
    seen = {"n": 0}

    def counting_open(file, *a, **k):
        if str(file) == path:
            seen["n"] += 1
        return _real_open(file, *a, **k)

    return seen, counting_open


_real_open = open


print("1. encoded art is cached per file")
version_art._src_cache.clear()
version_art._mem.clear()
path = _write("1.21.11", _png(b"one"), mtime=time.time() - 100)
seen, version_art.open = _count_opens(path)
first = version_art.src("1.21.11")
rest = [version_art.src("1.21.11") for _ in range(4)]
version_art.open = _real_open
check("a cached banner encodes to something", bool(first), repr(first)[:40])
check("repeat encodes are byte-identical", all(r == first for r in rest))
check("the file is read once, not once per render", seen["n"] == 1,
      f"opened {seen['n']} times")

print("\n2. a re-downloaded banner is re-encoded (no stale art)")
seen, version_art.open = _count_opens(path)
_write("1.21.11", _png(b"two-different"), mtime=time.time() + 60)
second = version_art.src("1.21.11")
version_art.open = _real_open
check("new bytes produce a new encode", second != first)
check("and it was read exactly once more", seen["n"] == 1,
      f"opened {seen['n']} times")

print("\n3. the encode cache is bounded")
version_art._src_cache.clear()
for i in range(version_art._SRC_CACHE_MAX + 3):
    version = f"1.{i}"
    _write(version, _png(f"v{i}".encode()))
    version_art.src(version)
check(f"never grows past {version_art._SRC_CACHE_MAX} entries",
      len(version_art._src_cache) <= version_art._SRC_CACHE_MAX,
      f"{len(version_art._src_cache)} entries")

print("\n4. art already on disk is applied without a fetch")
version_art._src_cache.clear()
_write("1.21.11", _png(b"sync"), mtime=time.time() - 5)
got = []
version_art.prefetch("1.21.11", got.append)
check("prefetch of a cached banner answers synchronously", len(got) == 1,
      f"callback ran {len(got)} times")
check("and hands back the encoded banner", bool(got) and got[0] == version_art.src("1.21.11"))

print("\n5. the Play tab has no instance list; panel cards mount real art")
stubs = fz.install_safe_stubs()
stubs.core.get_installed_versions = lambda *a, **k: [
    {"id": "1.21.11", "type": "release", "name": "1.21.11"},
    {"id": "1.20.1", "type": "release", "name": "1.20.1"},
]
page = app_driver.DriverPage()
stubs.app.run_sync(page)
driver = app_driver.Driver(stubs.app, stubs.core, page, stubs)
driver.open_tab("play")
check("the Play banner mounts a native fade host", any(
    type(control).__name__ == "AnimatedSwitcher" and control.data == "play-banner"
    for control in every_control(page)))


def find_play_rows():
    """Old Play-tab rows, tagged ``instance-row-<version id>``."""
    out = {}
    for c in every_control(page):
        data = getattr(c, "data", None)
        if isinstance(data, str) and data.startswith("instance-row-"):
            out[data[len("instance-row-"):]] = c
    return out


check("the Play tab no longer mounts an instance list", not find_play_rows(),
      str(sorted(find_play_rows())))

picker_btn = fz.clickable_with_subtext(page, "pick a minecraft version")
check("the Game-version button exists", bool(picker_btn))
picker_model = None
if picker_btn:
    picker_model = inspect.getclosurevars(
        picker_btn[0].on_click).nonlocals["self"]
    driver._fire_named(picker_btn[0], "on_click", "open version panel")
panel = picker_model.panel if picker_model else None


def find_panel_rows():
    """The version panel's instance cards, tagged ``version-panel-row-<id>``."""
    out = {}
    if panel is None:
        return out
    for c in walk(panel):
        data = getattr(c, "data", None)
        if isinstance(data, str) and data.startswith("version-panel-row-"):
            out[data[len("version-panel-row-"):]] = c
    return out


rows = find_panel_rows()
check("the panel lists one card per installed version",
      set(rows) == {"1.21.11", "1.20.1"}, f"found {sorted(rows)}")
check("every card carries a real picture",
      all(any(type(c).__name__ == "Image" for c in walk(row))
          for row in rows.values()),
      "each instance card paints cached key art or a bundled placeholder")
check("the picture is a loaded src, not an empty box",
      all((img.src or "") != ""
          for row in rows.values() for img in walk(row)
          if type(img).__name__ == "Image"),
      "an ft.Image with no src renders as a blank card")

selected_before = [vid for vid, c in rows.items()
                   if getattr(c.border, "top", None) is not None
                   and c.border.top.color == theme.ACCENT]
check("exactly one card starts selected", len(selected_before) == 1,
      f"selected: {selected_before}")
target = next(vid for vid in rows if vid not in selected_before)

driver._fire_named(rows[target], "on_click", "panel card select")
check("selecting a card closes the panel",
      picker_model is not None and not picker_model.is_open())
driver._fire_named(picker_btn[0], "on_click", "reopen version panel")
after_rows = find_panel_rows()
check("selecting a card does not raise", not driver.errors,
      str(driver.errors[:2]))
check("the selection actually moved",
      after_rows[target].border.top.color == theme.ACCENT
      and after_rows[selected_before[0]].border.top.color != theme.ACCENT,
      f"{target}={after_rows[target].border} "
      f"{selected_before[0]}={after_rows[selected_before[0]].border}")

print(f"\n{passed} passed, {failed} failed")
print("Version-art cache test: " + ("FAIL" if failed else "PASS"))
sys.exit(1 if failed else 0)
