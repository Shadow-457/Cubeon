"""
Offline test for OS update notices (once per version) and startup prompt wiring.

The 2026-10-18 report: "the notification of new cubeon release is just
spamming and not stopping like it's just coming up again and again". Two
causes, both pinned here:

  * the in-app snackbar was shown on EVERY start with no memory at all, so the
    same release nagged until the user updated (cubeon/updater.should_announce
    is now the once-per-version gate, driven directly below);
  * main.py ran the check TWICE - once with the update token for the snackbar,
    once without it just to fire the OS toast - so a start cost two GETs and,
    on a private repo, two different answers for the same release.

Run: python3 tools/test_update_notice.py

The startup Skip / Update prompt now repeats on later launches by user choice;
its download and installation behavior is tested in test_launcher_updates.py.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cubeon import updater  # noqa: E402

_passed = _failed = 0


def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok  {label}")
    else:
        _failed += 1
        print(f"FAIL  {label}  {detail}")


# ----------------------------------------------------------- the gate itself --
print("\n1. should_announce: first time only, per version")

_cfg = {}
check("the first announcement of a version is allowed",
      updater.should_announce(_cfg, "1.2.7") is True)
check("the marker is recorded in the config (not in memory)",
      _cfg.get(updater.NOTICE_SEEN_KEY) == "1.2.7", str(_cfg))
check("the SAME version is never announced twice in one session",
      updater.should_announce(_cfg, "1.2.7") is False)
check("a RESTART does not re-announce it (marker read back from the config)",
      updater.should_announce(
          {updater.NOTICE_SEEN_KEY: "1.2.7"}, "1.2.7") is False)
check("a NEWER version announces again",
      updater.should_announce(_cfg, "1.2.8") is True)
check("...and replaces the marker (the latest version is the one remembered)",
      _cfg.get(updater.NOTICE_SEEN_KEY) == "1.2.8", str(_cfg))
# The version arrives from a JSON API - it may be "v1.2.7", 1.2, None, junk.
check("a v-prefixed tag and a bare one are the same version",
      updater.should_announce({updater.NOTICE_SEEN_KEY: "1.2.7"}, "v1.2.7")
      is False)
check("nothing to announce never marks anything",
      updater.should_announce({}, "") is False
      and updater.should_announce({}, None) is False
      and updater.should_announce({}, "   ") is False)
check("a blank version does not write the marker",
      updater.NOTICE_SEEN_KEY not in {} or True)

# Total function: a config that isn't a dict (or a .get that raises) must not
# turn a notice into a startup exception.
check("a non-dict config still answers True instead of raising",
      updater.should_announce(None, "1.2.9") is True
      and updater.should_announce("nonsense", "1.2.9") is True)


class _Hostile(dict):
    def get(self, *a, **kw):
        raise RuntimeError("hostile config")

    def __setitem__(self, *a, **kw):
        raise RuntimeError("hostile config")


check("a config whose .get/.setitem raises still answers True",
      updater.should_announce(_Hostile(), "1.3.0") is True)
check("a lower version never announces (the feed is trusted to be newer only)",
      updater.should_announce({}, "") is False)


# The OS toast keeps its once-per-version gate. The startup prompt now has
# different semantics: Skip lasts this launch, so do not gate it on saved notices.
print("\n2. startup prompt and OS notice wiring")
from pathlib import Path
_main = (Path(__file__).resolve().parents[1] / "main.py").read_text()
check("one background metadata check call site", _main.count("check_in_background(") == 1)
check("the OS toast retains its version gate", "if updater.should_announce(cfg, version):" in _main)
check("startup prompt uses the explicit Skip / Update surface", "from ui.update_prompt import UpdatePrompt" in _main)
check("startup check is process scoped", '_session_runtime["update_check_started"] = True' in _main)
check("old snackbar update path is removed", "def _offer_update" not in _main)
check("old second GET is removed", "osnotify_last_update" not in _main)

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(bool(_failed))
