"""
Offline regression suite for the FPS-boost install path (cubeon/perf_mods.py)
and the frame-rate unlocker (cubeon/game_options.py).

The point of the feature: the Cubeon Client is a social mod, so "activate
Cubeon Client" must also bring the mods that actually raise frame rate
(Sodium, Lithium, ImmediatelyFast, EntityCulling, MoreCulling, ...) AND unlock
Minecraft's own Vsync/FPS-cap options. These tests pin the install/skip/fail
behaviour and the options rewrite with no network and no real profile:

  - a clean profile gets the whole suite, in order;
  - one/both already present (by slug, display name, project id or filename)
    -> kept, never re-downloaded (a duplicate Sodium is a crash, not a boost);
  - only Fabric/Quilt get anything; vanilla/Forge is a clean no-op;
  - every failure (no build, download error) is reported, never raised;
  - options.txt: only enableVsync and maxFps are touched, atomically and
    idempotently, and a file without those keys is left alone.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home  # noqa: E402
_sandbox_home.isolate()

import cubeon.perf_mods as perf  # noqa: E402
import cubeon.game_options as game_options  # noqa: E402
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

ALL_SLUGS = list(perf.PERF_MOD_SLUGS)


def _wire(installed, download=None, download_raises=False):
    perf.list_mods = lambda mc, ld: list(installed)
    perf.get_mod_download = lambda slug, mc_version=None, loader=None: dict(FILE, filename=slug + ".jar")
    calls = []

    def _dl(url, filename, **kw):
        if download_raises:
            raise OSError("disk full")
        calls.append((filename, kw.get("slug"), kw.get("project_id")))
        return "/tmp/" + filename

    perf.download_mod = _dl
    return calls


print("1. a clean profile gets the whole performance suite, in order")
calls = _wire([])
report = perf.ensure_installed("1.21.11", "fabric")
check("all installed", report["installed"] == ALL_SLUGS, f"got {report!r}")
check("downloaded in slug order", [c[1] for c in calls] == ALL_SLUGS,
      f"got {calls!r}")
check("project ids are recorded on install",
      all(c[2] for c in calls), f"got {calls!r}")
check("sodium and lithium are first",
      calls[0][1] == "sodium" and calls[1][1] == "lithium", f"got {calls[0:2]!r}")
# Now the profile really holds them.
perf.list_mods = lambda mc, ld: [
    {"slug": s, "display_name": s.title(), "filename": s + ".jar"}
    for s in ALL_SLUGS
]
check("is_installed now true", perf.is_installed("1.21.11", "fabric"))

print("\n2. already-present mods are never re-downloaded")
calls = _wire([
    {"slug": "sodium", "display_name": "Sodium", "filename": "sodium-0.6.jar"},
    {"project_id": "gvQqBUqZ", "display_name": "Lithium", "filename": "lithium-0.13.jar"},
])
report = perf.ensure_installed("1.21.11", "fabric")
check("sodium+lithium kept", {"sodium", "lithium"} <= set(report["kept"]), f"got {report!r}")
check("neither re-downloaded", not ({"sodium", "lithium"} & set(report["installed"])), f"got {report!r}")

print("\n3. a manual jar with a different filename still counts")
calls = _wire([
    {"slug": None, "display_name": "Sodium Extra",
     "filename": "sodium-fabric-0.9.2.jar"},
])
report = perf.ensure_installed("1.21.11", "fabric")
check("sodium detected from filename only",
      "sodium" in report["kept"], f"got {report!r}")
check("sodium not downloaded", "sodium" not in [c[1] for c in calls],
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
check("no build -> failed list", report["failed"] == ALL_SLUGS, f"got {report!r}")

_wire([], download_raises=True)
report = perf.ensure_installed("1.21.11", "quilt")
check("download error -> failed list", report["failed"] == ALL_SLUGS, f"got {report!r}")

print("\n6. the launch command carries the client GC tuning")
check("G1GC requested", any("UseG1GC" in f for f in CLIENT_JVM_FLAGS),
      f"got {CLIENT_JVM_FLAGS!r}")
check("heap Xms/Xmx are matched in the built args",
      "-Xms{ram_mb}M" in open(
          os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "cubeon", "launch.py"), encoding="utf-8").read())
check("pause goal is the non-aggressive value",
      "-XX:MaxGCPauseMillis=200" in CLIENT_JVM_FLAGS, f"got {CLIENT_JVM_FLAGS!r}")
check("heap-waste flag present", "-XX:G1HeapWastePercent=5" in CLIENT_JVM_FLAGS,
      f"got {CLIENT_JVM_FLAGS!r}")
check("LWJGL pointer checks disabled",
      "-Dorg.lwjgl.util.NoChecks=true" in CLIENT_JVM_FLAGS, f"got {CLIENT_JVM_FLAGS!r}")

_wire([{"slug": "sodium-extra", "display_name": "Sodium Extra",
        "filename": "sodium-extra-fabric-0.9.2.jar"}])
check("Sodium Extra never satisfies Sodium", "sodium" not in perf._present("1.20.1", "fabric"))
_wire([{"project_id": "AANobbMI"}, {"project_id": "gvQqBUqZ"}])
check("opaque performance project IDs are recognized",
      {"sodium", "lithium"} <= perf._present("1.20.1", "fabric"))

print("\n7. the frame-rate unlocker touches only vsync + the FPS cap")
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "options.txt")
    original = (
        "version:4671\n"
        "renderDistance:8\n"
        "enableVsync:true\n"
        "maxFps:70\n"
        "fullscreen:false\n"
        "resourcePacks:[\"vanilla\"]\n"
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(original)

    result = game_options.unlock_frame_rate(path)
    check("both keys reported changed",
          set(result["changed"]) == {"enableVsync", "maxFps"}, f"got {result!r}")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    check("vsync now false", "enableVsync:false" in text, repr(text))
    check("fps cap lifted", "maxFps:260" in text, repr(text))
    check("trailing newline preserved", text.endswith("\n"), repr(text[-5:]))
    check("other options untouched",
          "renderDistance:8" in text and "fullscreen:false" in text
          and "resourcePacks:[\"vanilla\"]" in text, repr(text))
    check("exactly one line changed per key",
          text.count("enableVsync:") == 1 and text.count("maxFps:") == 1, repr(text))
    check("original had a trailing newline too", original.endswith("\n"))

    second = game_options.unlock_frame_rate(path)
    check("idempotent: second run is a no-op",
          second["changed"] == [] and second["detail"] == "frame rate already unlocked",
          f"got {second!r}")

    check("missing file is reported, not raised",
          game_options.unlock_frame_rate(os.path.join(tmp, "nope.txt"))["changed"] == [])

with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "options.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("renderDistance:12\nmaxFps:120\n")  # no enableVsync key
    before = open(path, encoding="utf-8").read()
    result = game_options.unlock_frame_rate(path)
    after = open(path, encoding="utf-8").read()
    check("maxFps still raised when under the cap", "maxFps:260" in after, repr(after))
    check("no unknown enableVsync key invented",
          "enableVsync" not in after and before != after, repr(after))
    check("only maxFps reported", result["changed"] == ["maxFps"], f"got {result!r}")

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
