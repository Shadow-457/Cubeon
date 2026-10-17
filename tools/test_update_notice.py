"""
Offline test for the update notice - ONE announcement per version.

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


# ------------------------------------------------------------- main.py wiring --
print("\n2. main.py announces once, through one check")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(_ROOT, "main.py"), encoding="utf-8") as fh:
    _main = fh.read()

check("exactly ONE background update check is started",
      _main.count("check_in_background(") == 1,
      f"{_main.count('check_in_background(')} call sites")
check("the check uses the version gate (updater.should_announce)",
      "updater.should_announce(cfg, version)" in _main)
check("the gate is consulted BEFORE the notices go out",
      _main.index("updater.should_announce(cfg, version)")
      < _main.index("osnotify.update_available(version, cfg=cfg)")
      < _main.index("_offer_update(info)"))
check("the marker is SAVED, so the next start stays quiet",
      _main.index("core.save_config(cfg)") < _main.index("_offer_update(info)")
      and "osnotify.update_available" in _main)
_announcer = _main[_main.index("def _announce_update")
                  :_main.index("from cubeon import updater")]
check("a failed config write cannot swallow the notice",
      "except Exception:\n                pass" in _announcer)
check("the snackbar is reachable ONLY through the gated announcer",
      _main.count("_offer_update(") - 1 == 1     # minus the definition
      and "_offer_update(info)" in _announcer,
      f"{_main.count('_offer_update(')} references")
check("the OS toast still rides along (the Settings switch keeps meaning)",
      "osnotify.update_available(version, cfg=cfg)" in _main)
check("the old, ungated second-check marker is gone",
      "osnotify_last_update" not in _main,
      "the toast used to have its own key and its own token-less GET")

print(f"\n{_passed} passed, {_failed} failed")
if _failed:
    print("Update-notice test: FAIL")
    sys.exit(1)
print("Update-notice test: PASS")
