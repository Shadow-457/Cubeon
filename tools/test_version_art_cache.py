#!/usr/bin/env python3
"""
The Play tab's thumbnails must not reload themselves.

Reported symptom: the version art on the launcher's main menu re-loads over and
over. Two independent causes, both fixed here and both pinned by this file:

  1. `version_art.src()` is called from the RENDER path - on every selection
     change, for the version spotlight and for every "Jump back in" card. It
     re-opened the file and base64-encoded it again on each call (Mojang's key
     art is a 27-53 KB JPEG; measured 0.127 ms per uncached call on this
     machine). The encoded string is now cached per file, keyed by
     (mtime, size) so a re-downloaded banner can never serve a stale encode.

  2. `_rebuild_instance_cards()` had the SELECTED version in its change
     signature, so picking a version discarded and rebuilt every card. A
     rebuilt ft.Image is a brand-new control: Flet cannot diff it against the
     old one, so it re-sends the whole (base64) payload and every thumbnail in
     the row reloads on the client. This is the expensive half - a measured
     416 KB of art for six installed versions, re-sent per selection change.
     Selection is now a border/fill restyle, which sends two fields.

  3. Renaming an instance used to re-create its card, and the row was then
     re-assigned as a whole (`row.controls = [...]`). Flet tracks a plain
     `controls` reassignment as a structural change and patches it as a
     whole-list REPLACE, so ONE renamed card re-sent EVERY thumbnail in the
     row. The label is now edited in place and the row list is mutated
     (`row.controls[:] = [...]`), which Flet diffs child by child.

The card half is checked against the REAL built UI through tools/app_driver,
because the invariant is object identity of the live controls - which is
exactly what a re-created widget breaks.

No network: version_art's transport is replaced with a loud failure, so any
attempt to fetch during this test is an error rather than a live request.

Run: python3 tools/test_version_art_cache.py
"""
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
from _fuzz_common import every_control                      # noqa: E402
from cubeon import theme, version_art                       # noqa: E402
from ui.versions import InstanceCards                       # noqa: E402

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

print("\n5. the Jump back in row keeps its cards across a selection change")
stubs = fz.install_safe_stubs()
stubs.core.get_installed_versions = lambda *a, **k: [
    {"id": "1.21.11", "type": "release", "name": "1.21.11"},
    {"id": "1.20.1", "type": "release", "name": "1.20.1"},
]
page = app_driver.DriverPage()

# Keep a handle to the live InstanceCards the real app builds, so the rename
# and reorder invariants below are checked against the production row.
_live_cards = {}
_real_init = InstanceCards.__init__


def _capturing_init(self, *args, **kwargs):
    _real_init(self, *args, **kwargs)
    _live_cards["instance"] = self


InstanceCards.__init__ = _capturing_init

stubs.app.run_sync(page)
driver = app_driver.Driver(stubs.app, stubs.core, page, stubs)
driver.open_tab("play")   # the row lives on the Play tab
check("the Play banner mounts a native fade host", any(
    type(control).__name__ == "AnimatedSwitcher" and control.data == "play-banner"
    for control in every_control(page)))


def find_cards():
    """The instance cards: row-width Containers whose click handler carries the
    version id as its single default argument
    (`lambda e, k=version_id: _select_instance(k)`) - the same convention
    app_driver.tabs() uses to recover nav keys, and exact where a text or
    tooltip match is not."""
    out = {}
    for c in every_control(page):
        handler = getattr(c, "on_click", None)
        defaults = getattr(handler, "__defaults__", None)
        width = getattr(c, "width", None)
        if callable(handler) and isinstance(defaults, tuple) \
                and len(defaults) == 1 and isinstance(defaults[0], str) \
                and width is not None and float(width) == 210:
            out[defaults[0]] = c
    return out


def art_of(card):
    try:
        return card.content.controls[0].content
    except Exception:
        return None


cards = find_cards()
check("the row has one card per installed version",
      set(cards) == {"1.21.11", "1.20.1"}, f"found {sorted(cards)}")
check("each card holds a version-art image",
      all(type(art_of(c)).__name__ == "Image" for c in cards.values()),
      str({v: type(art_of(c)).__name__ for v, c in cards.items()}))

selected_before = [vid for vid, c in cards.items()
                   if c.bgcolor == theme.ACCENT_TINT]
check("exactly one card starts selected", len(selected_before) == 1,
      f"selected: {selected_before}")
target = next(vid for vid in cards if vid not in selected_before)

before = {vid: (id(c), id(art_of(c))) for vid, c in cards.items()}
driver._fire_named(cards[target], "on_click", "jump-back-in")
after_cards = find_cards()

check("selecting a version does not raise", not driver.errors,
      str(driver.errors[:2]))
check("the selection actually moved",
      after_cards[target].bgcolor == theme.ACCENT_TINT
      and after_cards[selected_before[0]].bgcolor == theme.CARD_FILL,
      f"{target}={after_cards[target].bgcolor} "
      f"{selected_before[0]}={after_cards[selected_before[0]].bgcolor}")
check("every card is the SAME widget (no rebuild -> no image resend)",
      all(id(after_cards[vid]) == before[vid][0] for vid in before),
      "card containers were re-created")
check("and every card still holds the SAME image widget",
      all(id(art_of(after_cards[vid])) == before[vid][1] for vid in before),
      "art controls were re-created")

print("\n6. renaming an instance edits its label in place")
instance_cards = _live_cards["instance"]
row_list = instance_cards.row.controls
labels = {}
instance_cards.get_labels = lambda: labels
before = {vid: (id(c), id(art_of(c))) for vid, c in find_cards().items()}
labels["1.20.1"] = "SmokePilot"
instance_cards.rebuild()
after_cards = find_cards()

check("the card is the SAME widget after a rename",
      all(id(after_cards[vid]) == before[vid][0] for vid in before),
      "a rename re-created the card")
check("and it still holds the SAME image widget",
      all(id(art_of(after_cards[vid])) == before[vid][1] for vid in before),
      "a rename re-created the art control")
check("the row list was mutated in place, not reassigned",
      instance_cards.row.controls is row_list,
      "row.controls was replaced -> Flet re-sends every child")
check("the card shows the new name",
      after_cards["1.20.1"].content.controls[1].content.controls[0].value
      == "SmokePilot")
check("the tooltip follows the new name",
      after_cards["1.20.1"].tooltip == "Select SmokePilot")

print("\n7. a reorder keeps the cards (and their images) alive")
metas = dict(instance_cards.get_metas())
instance_cards.get_metas = lambda: dict(reversed(list(metas.items())))
before = {vid: (id(c), id(art_of(c))) for vid, c in find_cards().items()}
instance_cards.rebuild()
reordered = find_cards()

check("a reorder does not re-create any card",
      all(id(reordered[vid]) == before[vid][0] for vid in before),
      "a reorder re-created a card")
check("nor any image",
      all(id(art_of(reordered[vid])) == before[vid][1] for vid in before),
      "a reorder re-created an art control")
check("and the row list is still the same object",
      instance_cards.row.controls is row_list,
      "row.controls was replaced -> Flet re-sends every child")
check("the cards follow the new order",
      [id(c) for c in instance_cards.row.controls]
      == [before[vid][0] for vid in reversed(list(metas))])

print(f"\n{passed} passed, {failed} failed")
print("Version-art cache test: " + ("FAIL" if failed else "PASS"))
sys.exit(1 if failed else 0)
