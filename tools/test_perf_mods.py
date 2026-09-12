"""
Offline regression suite for the FPS-boost install path
(cubeon/perf_mods.py).

The point of the feature: the Cubeon Client is a social mod, so "activate
Cubeon Client" must also bring the mods that actually raise frame rate
(Sodium + Lithium). These tests pin the install/skip/fail behaviour with no
network and no real profile:

  - both missing -> both fetched, in order;
  - one/both already present (by slug, display name, project id or filename)
    -> kept, never re-downloaded (a duplicate Sodium is a crash, not a boost);
  - only Fabric/Quilt get anything; vanilla/Forge is a clean no-op;
  - every failure (no build, download error) is reported, never raised.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home  # noqa: E402
_sandbox_home.isolate()

import cubeon.perf_mods as perf  # noqa: E402
from cubeon.launch import CLIENT_JVM_FLAGS  # noqa: E402

_passed = _failed = 0


def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok  {label}")
    else:
        _failed += 1
        print(f"FAIL  {label}  {detail}")


FILE = {"filename": "sodium.jar", "url": "https://example/sodium.jar",
        "hashes": {"sha1": "x"}, "version_number": "1"}


def _wire(installed, download=None, download_raises=False):
    perf.list_mods = lambda mc, ld: list(installed)
    perf.get_mod_download = lambda slug, mc_version=None, loader=None: dict(FILE, filename=slug + ".jar")
    calls = []

    def _dl(url, filename, **kw):
        if download_raises:
            raise OSError("disk full")
        calls.append((filename, kw.get("slug")))
        return "/tmp/" + filename

    perf.download_mod = _dl
    return calls


print("1. a clean profile gets both performance mods, in order")
calls = _wire([])
report = perf.ensure_installed("1.21.11", "fabric")
check("both installed", report["installed"] == ["sodium", "lithium"],
      f"got {report!r}")
check("downloaded in slug order", [c[1] for c in calls] == ["sodium", "lithium"],
      f"got {calls!r}")
# Now the profile really holds them.
perf.list_mods = lambda mc, ld: [
    {"slug": "sodium", "display_name": "Sodium", "filename": "sodium.jar"},
    {"slug": "lithium", "display_name": "Lithium", "filename": "lithium.jar"},
]
check("is_installed now true", perf.is_installed("1.21.11", "fabric"))

print("\n2. already-present mods are never re-downloaded")
calls = _wire([
    {"slug": "sodium", "display_name": "Sodium", "filename": "sodium-0.6.jar"},
    {"project_id": "lithium", "display_name": "Lithium", "filename": "lithium-0.13.jar"},
])
report = perf.ensure_installed("1.21.11", "fabric")
check("both kept", sorted(report["kept"]) == ["lithium", "sodium"], f"got {report!r}")
check("nothing downloaded", calls == [], f"got {calls!r}")

print("\n3. a manual jar with a different filename still counts")
calls = _wire([
    {"slug": None, "display_name": "Sodium Extra",
     "filename": "sodium-fabric-0.9.2.jar"},
])
report = perf.ensure_installed("1.21.11", "fabric")
check("sodium detected from filename only",
      "sodium" in report["kept"], f"got {report!r}")
check("only lithium downloaded", [c[1] for c in calls] == ["lithium"],
      f"got {calls!r}")

print("\n4. non-Fabric loaders are a no-op")
for loader in ("forge", "neoforge", "vanilla", None):
    calls = _wire([])
    report = perf.ensure_installed("1.21.11", loader)
    check(f"{loader!r}: nothing installed",
          report["installed"] == [] and calls == [], f"got {report!r}")

print("\n5. failures are reported, never raised")
perf.list_mods = lambda mc, ld: []
perf.get_mod_download = lambda slug, **kw: None
report = perf.ensure_installed("1.21.11", "quilt")
check("no build -> failed list", report["failed"] == ["sodium", "lithium"],
      f"got {report!r}")

_wire([], download_raises=True)
report = perf.ensure_installed("1.21.11", "quilt")
check("download error -> failed list", report["failed"] == ["sodium", "lithium"],
      f"got {report!r}")

print("\n6. the launch command carries the client GC tuning")
check("G1GC requested", any("UseG1GC" in f for f in CLIENT_JVM_FLAGS),
      f"got {CLIENT_JVM_FLAGS!r}")
check("heap Xms/Xmx are matched in the built args",
      "-Xms{ram_mb}M" in open(
          os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "cubeon", "launch.py"), encoding="utf-8").read())

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
