"""
Offline regression suite for the FPS-boost install path (cubeon/perf_mods.py)
and the options.txt appliers (cubeon/game_options.py).

The point of the feature: the Cubeon Client is a social mod, so "activate
Cubeon Client" must also bring the mods that actually raise frame rate
(Sodium, Lithium, ImmediatelyFast, EntityCulling, MoreCulling, ...). It must
NOT touch Vsync/maxFps - those belong to the player. These tests pin the
install/skip/fail behaviour and the options rewrite with no network and no
real profile:

  - a clean profile gets the whole suite, in order;
  - one/both already present (by slug, display name, project id or filename)
    -> kept, never re-downloaded (a duplicate Sodium is a crash, not a boost);
  - only Fabric/Quilt get anything; vanilla/Forge is a clean no-op;
  - every failure (no build, download error) is reported, never raised;
  - options.txt: graphics keys are rewritten atomically and idempotently,
    enableVsync/maxFps are never read or written.
"""
import json as _json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home  # noqa: E402
_sandbox_home.isolate()

import cubeon.perf_mods as perf  # noqa: E402
import cubeon.game_options as game_options  # noqa: E402
from cubeon.launch import (CLIENT_JVM_FLAGS, client_jvm_flags,  # noqa: E402
                           _initial_heap_mb, _pretouch_flag)

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


print("1. a clean profile gets the performance suite, in order")
calls = _wire([])
report = perf.ensure_installed("1.21.11", "fabric")
check("all installed", report["installed"] == ALL_SLUGS, f"got {report!r}")
check("downloaded in slug order", [c[1] for c in calls] == ALL_SLUGS,
      f"got {calls!r}")
check("project ids are recorded on install",
      all(c[2] for c in calls), f"got {calls!r}")
check("sodium installs first (biggest win), then the companions",
      calls[0][1] == "sodium" and len(calls) == len(ALL_SLUGS), f"got {calls!r}")
# Now the profile really holds them.
perf.list_mods = lambda mc, ld: [
    {"slug": s, "display_name": s.title(), "filename": s + ".jar"}
    for s in ALL_SLUGS
]
check("is_installed now true", perf.is_installed("1.21.11", "fabric"))

print("\n2. already-present mods are never re-downloaded")
calls = _wire([
    {"slug": "sodium", "display_name": "Sodium", "filename": "sodium-0.6.jar"},
])
report = perf.ensure_installed("1.21.11", "fabric")
check("sodium kept", "sodium" in report["kept"], f"got {report!r}")
check("sodium not re-downloaded", "sodium" not in [c[1] for c in calls],
      f"got {calls!r}")
# A profile holding a suite mod by a hand-dropped jar counts for that mod.
calls = _wire([
    {"slug": "lithium", "display_name": "Lithium", "filename": "lithium-0.13.jar"},
])
report = perf.ensure_installed("1.21.11", "fabric")
check("hand-dropped lithium is kept, the rest installed",
      report["kept"] == ["lithium"]
      and report["installed"] == [s for s in ALL_SLUGS if s != "lithium"],
      f"got {report!r}")

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
_launch_src = open(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "cubeon", "launch.py"), encoding="utf-8").read()
check("the JVM is not asked to commit the whole heap (-Xms != -Xmx)",
      "-Xms{ram_mb}M" not in _launch_src and "_initial_heap_mb(ram_mb)" in _launch_src,
      "an -Xms equal to -Xmx commits and pins the whole heap (F3: Allocated 100%)")
check("a small -Xmx is never given a bigger -Xms",
      _initial_heap_mb(4096) == 512 and _initial_heap_mb(256) == 256,
      f"got {_initial_heap_mb(4096)!r} / {_initial_heap_mb(256)!r}")
check("pause goal is the non-aggressive value",
      "-XX:MaxGCPauseMillis=200" in CLIENT_JVM_FLAGS, f"got {CLIENT_JVM_FLAGS!r}")
check("heap-waste flag present", "-XX:G1HeapWastePercent=5" in CLIENT_JVM_FLAGS,
      f"got {CLIENT_JVM_FLAGS!r}")
check("LWJGL pointer checks disabled",
      "-Dorg.lwjgl.util.NoChecks=true" in CLIENT_JVM_FLAGS, f"got {CLIENT_JVM_FLAGS!r}")
check("G1 region size suits a client heap",
      all("-XX:G1HeapRegionSize=8M" in client_jvm_flags(n) for n in (2, 4, 8, 16)),
      f"got {client_jvm_flags(2)!r}")
check("low-core flags shrink the young gen",
      "-XX:G1NewSizePercent=10" in client_jvm_flags(2)
      and "-XX:MaxGCPauseMillis=100" in client_jvm_flags(3),
      f"got {client_jvm_flags(2)!r}")
check("many-core flags keep the young gen small (client, not Aikar server)",
      "-XX:G1NewSizePercent=10" in client_jvm_flags(8)
      and "-XX:G1MaxNewSizePercent=40" in client_jvm_flags(8)
      and "-XX:MaxGCPauseMillis=200" in client_jvm_flags(8),
      f"got {client_jvm_flags(8)!r}")
check("Aikar's server-only GC values are gone",
      all(flag not in client_jvm_flags(8) for flag in (
          "-XX:G1ReservePercent=20", "-XX:InitiatingHeapOccupancyPercent=15",
          "-XX:SurvivorRatio=32", "-XX:MaxTenuringThreshold=1")),
      f"got {client_jvm_flags(8)!r}")
check("exactly one collector flag in either tuning",
      sum(1 for f in client_jvm_flags(2)
          if f.startswith("-XX:+Use") and f.endswith("GC")) == 1
      and sum(1 for f in client_jvm_flags(16)
              if f.startswith("-XX:+Use") and f.endswith("GC")) == 1,
      f"got {client_jvm_flags(2)!r}")
check("AlwaysPreTouch is offered on a roomy box",
      _pretouch_flag(4096, 12288) == "-XX:+AlwaysPreTouch",
      f"got {_pretouch_flag(4096, 12288)!r}")
check("AlwaysPreTouch is withheld on low RAM",
      _pretouch_flag(4096, 6144) is None, f"got {_pretouch_flag(4096, 6144)!r}")
check("AlwaysPreTouch is withheld when the heap is most of RAM",
      _pretouch_flag(8192, 12288) is None, f"got {_pretouch_flag(8192, 12288)!r}")

_wire([{"slug": "sodium-extra", "display_name": "Sodium Extra",
        "filename": "sodium-extra-fabric-0.9.2.jar"}])
check("Sodium Extra never satisfies Sodium", "sodium" not in perf._present("1.20.1", "fabric"))
_wire([{"project_id": "AANobbMI"}, {"project_id": "gvQqBUqZ"}])
check("opaque performance project IDs are recognized",
      "sodium" in perf._present("1.20.1", "fabric")
      and "lithium" in perf._present("1.20.1", "fabric"))
check("retired project IDs are no longer recognized",
      "badoptimizations" not in perf._present("1.20.1", "fabric"))

print("\n7. options.txt: the launcher leaves Vsync/maxFps alone")
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "options.txt")
    original = (
        "version:4671\n"
        "renderDistance:8\n"
        "enableVsync:true\n"
        "maxFps:120\n"
        "graphicsPreset:\"fancy\"\n"
        "fullscreen:false\n"
        "resourcePacks:[\"vanilla\"]\n"
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(original)

    result = game_options.apply_max_fps(path)
    check("the graphics preset is rewritten",
          "graphicsPreset" in result["changed"], f"got {result!r}")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    check("Vsync is left exactly as the player had it",
          "enableVsync:true" in text, repr(text))
    check("the player's FPS cap is left alone",
          "maxFps:120" in text, repr(text))
    check("no Vsync/maxFps key is ever reported changed",
          "enableVsync" not in result["changed"]
          and "maxFps" not in result["changed"], f"got {result!r}")
    check("trailing newline preserved", text.endswith("\n"), repr(text[-5:]))
    check("other options untouched",
          "renderDistance:6" in text and "fullscreen:false" in text
          and "resourcePacks:[\"vanilla\"]" in text, repr(text))
    check("exactly one line changed per key",
          text.count("enableVsync:") == 1 and text.count("maxFps:") == 1,
          repr(text))
    check("original had a trailing newline too", original.endswith("\n"))

    second = game_options.apply_max_fps(path)
    check("idempotent: second run writes nothing",
          second["changed"] == [], f"got {second!r}")

    check("missing file is reported, not raised",
          game_options.apply_max_fps(os.path.join(tmp, "nope.txt"))["changed"] == [])

# The 2026-10-24 fan-noise fix: forcing enableVsync:false + maxFps:260 on
# every launch is gone for good. A fresh install keeps Minecraft's defaults
# (Vsync ON, maxFps 120) and an existing file is never rewritten.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_launch_now = open(os.path.join(_ROOT, "cubeon", "launch.py"),
                   encoding="utf-8").read()
_options_src = open(os.path.join(_ROOT, "cubeon", "game_options.py"),
                    encoding="utf-8").read()
check("the frame-rate unlocker is gone",
      not hasattr(game_options, "unlock_frame_rate"))
check("the launch path never rewrites Vsync or maxFps",
      "unlock_frame_rate" not in _launch_now
      and "game_options.VSYNC_KEY" not in _launch_now
      and "game_options.MAX_FPS_KEY" not in _launch_now,
      "forcing Vsync off on every launch pegged six cores in singleplayer")
check("no applier writes Vsync/maxFps keys",
      "VSYNC_KEY:" not in _options_src and "MAX_FPS_KEY:" not in _options_src,
      "the constants stay documented but no table may use them")

print("\n8. the EntityCulling config is repaired of crash-inducing entries")
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "entityculling.json")
    with open(path, "w", encoding="utf-8") as fh:
        _json.dump({
            "configVersion": 9,
            "sleepDelay": 125,
            "blockEntityWhitelist": ["minecraft:beacon", None,
                                     "botania:flame_ring"],
            "entityWhitelist": ["", "botania:mana_burst"],
            "tickCullingWhitelist": ["minecraft:boat", "   ",
                                     "minecraft:acacia_boat"],
        }, fh)

    result = perf.sanitize_entityculling_config(path)
    check("all bad entries removed", result["removed"] == 3, f"got {result!r}")
    with open(path, encoding="utf-8") as fh:
        fixed = _json.load(fh)
    check("null dropped from blockEntityWhitelist",
          fixed["blockEntityWhitelist"] == ["minecraft:beacon", "botania:flame_ring"],
          repr(fixed["blockEntityWhitelist"]))
    check("empty dropped from entityWhitelist",
          fixed["entityWhitelist"] == ["botania:mana_burst"],
          repr(fixed["entityWhitelist"]))
    check("blank dropped from tickCullingWhitelist",
          fixed["tickCullingWhitelist"] == ["minecraft:boat", "minecraft:acacia_boat"],
          repr(fixed["tickCullingWhitelist"]))
    check("unrelated options untouched",
          fixed["configVersion"] == 9 and fixed["sleepDelay"] == 125, repr(fixed))
    second = perf.sanitize_entityculling_config(path)
    check("idempotent: second run removes nothing", second["removed"] == 0,
          f"got {second!r}")

    check("missing config is safe",
          perf.sanitize_entityculling_config(os.path.join(tmp, "nope.json"))["removed"] == 0)

    bad = os.path.join(tmp, "bad.json")
    with open(bad, "w", encoding="utf-8") as fh:
        fh.write("[1, 2, 3]")
    check("non-object JSON is reported, not raised",
          perf.sanitize_entityculling_config(bad)["removed"] == 0)

print("\n9. retired perf mods are pruned from an existing profile")
_deleted = []
perf.list_mods = lambda mc, ld: [
    {"slug": "sodium", "project_id": "AANobbMI", "filename": "sodium.jar"},
    {"slug": "krypton", "project_id": "fQEb0iXm", "filename": "krypton.jar"},
    {"project_id": "vSEH1ERy", "filename": "threadtweak.jar"},
    {"slug": None, "project_id": None, "filename": "my-own-mod.jar"},
]
perf.delete_mod = lambda mc, ld, fn: _deleted.append(fn)
removed = perf.prune_retired_perf_mods("1.21.11", "fabric")
check("only the Cubeon-installed retired mods are deleted",
      sorted(_deleted) == ["krypton.jar", "threadtweak.jar"], f"got {_deleted!r}")
check("sodium and the hand-dropped jar survive",
      "sodium.jar" not in _deleted and "my-own-mod.jar" not in _deleted,
      f"got {_deleted!r}")
check("reports what it removed", len(removed) == 2, f"got {removed!r}")
check("non-Fabric loaders prune nothing",
      perf.prune_retired_perf_mods("1.21.11", "forge") == [])

print("\n10. Max FPS mode sets the speed-only graphics options")
go = game_options
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "options.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(
            "version:4671\n"
            "graphicsPreset:\"custom\"\n"
            "ao:true\n"
            "particles:0\n"
            "entityShadows:true\n"
            "entityDistanceScaling:1.0\n"
            "biomeBlendRadius:2\n"
            "syncChunkWrites:true\n"
            "renderDistance:12\n"
            "simulationDistance:12\n"
            "mipmapLevels:4\n"
            "renderClouds:\"true\"\n"
        )
    original = open(path, encoding="utf-8").read()
    result = go.apply_max_fps(path)
    check("every speed-only key applied, distance levers included",
          sorted(result["changed"]) == sorted(
              ["graphicsPreset", "particles", "ao", "entityShadows",
               "entityDistanceScaling", "biomeBlendRadius", "syncChunkWrites",
               "renderDistance", "simulationDistance", "mipmapLevels",
               "renderClouds"]),
          f"got {result!r}")
    text = open(path, encoding="utf-8").read()
    check("values are the fast ones",
          all(line in text for line in (
              'graphicsPreset:"fast"', "particles:2", "ao:false",
              "entityShadows:false", "entityDistanceScaling:0.75",
              "biomeBlendRadius:0", "syncChunkWrites:false")), repr(text))
    check("particles is MINIMAL (id 2), never ALL (id 0)", "particles:2" in text)
    check("the LIVE fast-graphics key is written, not the dead one",
          "graphicsPreset:" in text and "graphicsMode" not in text, repr(text))
    # 2026-10-18: the distance levers became part of the default config. A
    # side-by-side run against FastClient showed the frame-rate gap was almost
    # entirely these - Cubeon at renderDistance 8 meshes ~70% more chunks than
    # FastClient at 6, and the GPU was idle while both were Java-bound.
    check("the distance levers are lowered too",
          "renderDistance:6" in text and "simulationDistance:5" in text
          and "mipmapLevels:2" in text and 'renderClouds:"fast"' in text,
          repr(text))
    check("no lines added or removed",
          len(original.splitlines()) == len(text.splitlines()), repr(text))
    again = go.apply_max_fps(path)
    check("idempotent", again["changed"] == [] and "already applied" in again["detail"],
          f"got {again!r}")

    # A bare (unquoted) string value is normalised ONCE, then left alone - the
    # old code rewrote a quoted string on every single launch.
    with tempfile.TemporaryDirectory() as tmp:
        p2 = os.path.join(tmp, "options.txt")
        with open(p2, "w", encoding="utf-8") as fh:
            fh.write("graphicsPreset:custom\nparticles:0\n")
        first = go.apply_max_fps(p2)
        check("a bare string value is rewritten quoted",
              first["changed"] == ["graphicsPreset", "particles"]
              and 'graphicsPreset:"fast"' in open(p2, encoding="utf-8").read(),
              f"got {first!r}")
        second = go.apply_max_fps(p2)
        check("and stays put on the next launch (the old bug rewrote every time)",
              second["changed"] == [], f"got {second!r}")

with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "fresh.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("fov:1.0\n")
    result = go.apply_max_fps(path)
    check("a fresh options.txt is not given unknown keys",
          result["changed"] == [] and "not in options.txt" in result["detail"],
          f"got {result!r}")
    check("its only key survives untouched",
          open(path, encoding="utf-8").read() == "fov:1.0\n")

print("\n11. FPS boost OFF restores the vanilla look (the same keys, defaults)")
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "options.txt")
    # An options.txt as it looks after running with the boost ON for a while.
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(
            "version:4671\n"
            "graphicsPreset:\"fast\"\n"
            "ao:false\n"
            "particles:2\n"
            "entityShadows:false\n"
            "entityDistanceScaling:0.75\n"
            "biomeBlendRadius:0\n"
            "syncChunkWrites:false\n"
            "smoothLighting:true\n"
            "renderDistance:6\n"
            "simulationDistance:5\n"
            "mipmapLevels:2\n"
            "renderClouds:\"fast\"\n"
        )
    result = go.restore_vanilla_look(path)
    check("every boost key is restored, distance levers included",
          sorted(result["changed"]) == sorted(
              ["graphicsPreset", "particles", "ao", "entityShadows",
               "entityDistanceScaling", "biomeBlendRadius", "syncChunkWrites",
               "renderDistance", "simulationDistance", "mipmapLevels",
               "renderClouds"]),
          f"got {result!r}")
    text = open(path, encoding="utf-8").read()
    check("values are Minecraft's own defaults again",
          all(line in text for line in (
              'graphicsPreset:"fancy"', "particles:0", "ao:true",
              "entityShadows:true", "entityDistanceScaling:1.0",
              "biomeBlendRadius:2", "syncChunkWrites:true")), repr(text))
    check("smooth lighting stays true (never nerfed, never invented)",
          "smoothLighting:true" in text and "smoothLighting" not in result["changed"],
          repr(text))
    # FPS boost OFF has to hand the view distance back too, or "vanilla look
    # restored" would leave the player stuck at the boost's renderDistance 6
    # with no obvious way back.
    check("the distance levers go back to vanilla too",
          "renderDistance:12" in text and "simulationDistance:12" in text
          and "mipmapLevels:4" in text and 'renderClouds:"true"' in text,
          repr(text))
    again = go.restore_vanilla_look(path)
    check("restore is idempotent",
          again["changed"] == [] and "already applied" in again["detail"],
          f"got {again!r}")
    # And round-trips: boost on again after a restore.
    back = go.apply_max_fps(path)
    check("boost can be re-applied after a restore",
          sorted(back["changed"]) == sorted(
              ["graphicsPreset", "particles", "ao", "entityShadows",
               "entityDistanceScaling", "biomeBlendRadius", "syncChunkWrites",
               "renderDistance", "simulationDistance", "mipmapLevels",
               "renderClouds"]),
          f"got {back!r}")

with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "fresh.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("fov:1.0\n")
    result = go.restore_vanilla_look(path)
    check("restore never invents keys in a fresh options.txt",
          result["changed"] == [] and "not in options.txt" in result["detail"],
          f"got {result!r}")

print("\n12. Sodium's own renderer options are repaired on every boosted launch")
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "sodium-options.json")
    # A config that has drifted in every way that matters: the shape an older
    # Cubeon generation leaves behind, plus two of the flips an FPS guide
    # recommends (fog occlusion off) that cost frames for no visible win.
    drifted = {
        "quality": {
            "hidden_fluid_culling": False,        # wrong
            "improved_fluid_shaping": True,       # wrong
            "pixel_filtering_mode": "LINEAR",     # taste -> keep
            "use_closest_point_entity_sort": True,  # taste -> keep
        },
        "performance": {
            "chunk_builder_threads": 2,           # wrong (0 = all cores)
            "chunk_build_defer_mode": "ZERO_FRAMES",   # wrong
            "animate_only_visible_textures": False,    # wrong
            "use_entity_culling": False,               # wrong
            "use_fog_occlusion": False,                # wrong
            "use_block_face_culling": True,            # already fast
            "use_no_error_g_l_context": True,          # already fast
            "quad_splitting_mode": "OFF",              # wrong
        },
        "advanced": {
            "use_advanced_staging_buffers": True,      # already fast
            "cpu_render_ahead_limit": 1,               # wrong
        },
        "debug": {"terrain_sorting_enabled": True},
        # Sodium's own UI state, and a section from a Sodium that does not
        # exist yet: both must survive untouched.
        "notifications": {"has_seen_donation_prompt": False},
        "future_section": {"we_do_not_know": 1},
    }
    with open(path, "w", encoding="utf-8") as fh:
        _json.dump(drifted, fh)

    result = perf.apply_max_fps_sodium(path)
    check("only the options that were actually wrong are reported",
          sorted(result["changed"]) == sorted([
              "quality.hidden_fluid_culling", "quality.improved_fluid_shaping",
              "performance.chunk_builder_threads",
              "performance.chunk_build_defer_mode",
              "performance.animate_only_visible_textures",
              "performance.use_entity_culling",
              "performance.use_fog_occlusion",
              "performance.quad_splitting_mode",
              "advanced.cpu_render_ahead_limit"]),
          f"got {result!r}")
    fixed = _json.load(open(path, encoding="utf-8"))
    check("the renderer switches are back at the fast values",
          fixed["performance"]["use_fog_occlusion"] is True
          and fixed["performance"]["use_entity_culling"] is True
          and fixed["performance"]["animate_only_visible_textures"] is True
          and fixed["performance"]["chunk_build_defer_mode"] == "ALWAYS"
          and fixed["performance"]["quad_splitting_mode"] == "SAFE"
          and fixed["performance"]["chunk_builder_threads"] == 0
          and fixed["quality"]["hidden_fluid_culling"] is True
          and fixed["quality"]["improved_fluid_shaping"] is False
          and fixed["advanced"]["cpu_render_ahead_limit"] == 3,
          repr(fixed))
    check("the player's own taste is left alone",
          fixed["quality"]["pixel_filtering_mode"] == "LINEAR"
          and fixed["quality"]["use_closest_point_entity_sort"] is True,
          repr(fixed["quality"]))
    check("Sodium's own UI state and unknown sections survive",
          fixed["notifications"] == {"has_seen_donation_prompt": False}
          and fixed["future_section"] == {"we_do_not_know": 1}, repr(fixed))
    check("and no section was added or removed",
          set(fixed) == set(drifted), repr(sorted(fixed)))
    # The values are the ones Sodium itself compiles in: with the boost on
    # there is nothing for a later "restore" to write back.
    check("the fast values ARE Sodium's own defaults",
          perf.SODIUM_MAX_FPS_OPTIONS["quality"]["hidden_fluid_culling"] is True
          and perf.SODIUM_MAX_FPS_OPTIONS["performance"]["chunk_build_defer_mode"] == "ALWAYS"
          and perf.SODIUM_MAX_FPS_OPTIONS["performance"]["quad_splitting_mode"] == "SAFE"
          and perf.SODIUM_MAX_FPS_OPTIONS["advanced"]["use_advanced_staging_buffers"] is True)

    again = perf.apply_max_fps_sodium(path)
    check("idempotent: the next launch changes nothing",
          again["changed"] == [] and "already" in again["detail"], f"got {again!r}")

    # `0` is the number that spells `false` in JSON. Without a bool check the
    # repair would accept it as already-correct and leave the switch off.
    with open(path, "w", encoding="utf-8") as fh:
        _json.dump({"performance": {"use_fog_occlusion": 0,
                                    "use_block_face_culling": 1,
                                    "use_entity_culling": True}}, fh)
    numbers = perf.apply_max_fps_sodium(path)
    check("a 0/1 that means false/true is corrected, not accepted",
          numbers["changed"] == ["performance.use_fog_occlusion",
                                 "performance.use_block_face_culling"],
          f"got {numbers!r}")
    number_data = _json.load(open(path, encoding="utf-8"))["performance"]
    check("and is written as a real JSON boolean, not left as a number",
          number_data["use_fog_occlusion"] is True
          and number_data["use_block_face_culling"] is True, repr(number_data))
    check("a switch that was already a real boolean is not touched",
          "use_entity_culling" not in perf.apply_max_fps_sodium(path)["changed"])

    # A Sodium 0.4.x file (Minecraft 1.20) has none of the newer options. Only
    # the names both generations share may be touched - inventing
    # chunk_build_defer_mode in a 0.4.x file would be an unknown key.
    legacy_path = os.path.join(tmp, "legacy.json")
    with open(legacy_path, "w", encoding="utf-8") as fh:
        _json.dump({
            "quality": {"weather_quality": True, "leaves_quality": "fancy",
                        "enable_vignette": True},
            "performance": {"chunk_builder_threads": 1,
                            "always_defer_chunk_updates": False,
                            "use_entity_culling": True,
                            "use_fog_occlusion": False},
            "advanced": {"use_persistent_mapping": True},
            "notifications": {"has_cleared_donation_button": True},
        }, fh)
    legacy = perf.apply_max_fps_sodium(legacy_path)
    check("a legacy config gets the switches both generations share",
          legacy["changed"] == ["performance.chunk_builder_threads",
                                "performance.use_fog_occlusion"],
          f"got {legacy!r}")
    legacy_data = _json.load(open(legacy_path, encoding="utf-8"))
    check("and is never given a key its generation does not have",
          "chunk_build_defer_mode" not in legacy_data["performance"]
          and "quad_splitting_mode" not in legacy_data["performance"]
          and "hidden_fluid_culling" not in legacy_data["quality"],
          repr(legacy_data))

    missing = os.path.join(tmp, "nope", "sodium-options.json")
    result = perf.apply_max_fps_sodium(missing)
    check("no config file -> nothing written and nothing invented",
          result["changed"] == [] and not os.path.exists(missing)
          and "defaults" in result["detail"], f"got {result!r}")

    broken = os.path.join(tmp, "broken.json")
    with open(broken, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    check("a corrupt config is reported, never raised",
          perf.apply_max_fps_sodium(broken)["changed"] == [])
    with open(broken, "w", encoding="utf-8") as fh:
        fh.write("[1, 2, 3]")
    check("a non-object config is reported, never raised",
          perf.apply_max_fps_sodium(broken)["changed"] == [])

    check("the path is Sodium's own file in the game dir",
          perf.sodium_config_path().endswith(
              os.path.join("config", "sodium-options.json")))

# The launch path is the only caller that matters: the repair has to sit behind
# the same FPS boost toggle as the options.txt rewrite, and inside the perf
# block (a Sodium-only repair with Vsync still on would be half a boost).
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_launch_src = open(os.path.join(_REPO, "cubeon", "launch.py"), encoding="utf-8").read()
check("the launch path enforces Sodium's options on every boosted launch",
      'if cfg.get("fps_boost_enabled", True):\n'
      "                tuned = perf_mods.apply_max_fps_sodium()" in _launch_src,
      "expected the call directly under the fps_boost_enabled check")
check("it is not in the FPS-boost-OFF branch",
      _launch_src.index("tuned = perf_mods.apply_max_fps_sodium()")
      > _launch_src.index("restored = game_options.restore_vanilla_look()"),
      "Sodium's defaults are already the fast values - OFF must not rewrite it")

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
