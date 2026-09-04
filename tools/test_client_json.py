#!/usr/bin/env python3
"""
Tests for the client.json sanitizer, the emptied-arguments repair, and loader
version selection.

Covers three real bugs found after a launch failed with

    ClassNotFoundException: net.fabricmc.loader.impl.launch.knot.KnotClient

1. `_sanitize_client_json` DELETED every argument entry keyed "values" instead
   of "value" - and TLauncher spells every entry that way, so it wiped the whole
   arguments block, `-cp ${classpath}` included, then saved the damage to disk.
2. Two of the test machine's modpacks were left permanently broken by (1), so
   there has to be a repair path for installs that are already damaged.
3. `find_installed_loader_version` picked its result out of a *set*, so with two
   candidates for (1.21.11, fabric) it returned a different one run to run.

Run: python3 tools/test_client_json.py
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# --- sandbox: redirect HOME to a scratch dir before cubeon binds its paths at
# import time, so tests never read/write the developer's real game dir/store.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home
_sandbox_home.isolate()

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


# ---------------------------------------------------------------- fixtures ---

# An entry shaped the way TLauncher writes them: "values", not "value".
TLAUNCHER_JSON = {
    "id": "pack",
    "type": "release",
    "mainClass": "net.fabricmc.loader.impl.launch.knot.KnotClient",
    "libraries": [{"name": "net.fabricmc:fabric-loader:0.18.4"}],
    "arguments": {
        "game": [
            {"values": ["--username"]},
            {"values": ["${auth_player_name}"]},
            {"values": ["--version"]},
            {"values": ["${version_name}"]},
        ],
        "jvm": [
            {"values": ["-XstartOnFirstThread"],
             "rules": [{"action": "allow", "os": {"name": "osx"}}]},
            {"values": ["-Xss1M"], "rules": [{"action": "allow", "os": {}}]},
            {"values": ["-cp"]},
            {"values": ["${classpath}"]},
            {"values": ["-DFabricMcEmu= net.minecraft.client.main.Main "]},
        ],
    },
}

EMPTIED_JSON = {
    "id": "pack",
    "type": "release",
    "mainClass": "net.fabricmc.loader.impl.launch.knot.KnotClient",
    "libraries": [{"name": "net.fabricmc:fabric-loader:0.18.4"}],
    "arguments": {"game": [], "jvm": []},
}

VANILLA_JSON = {
    "id": "1.21.11",
    "type": "release",
    "mainClass": "net.minecraft.client.main.Main",
    "libraries": [],
    "arguments": {
        "game": ["--username", "${auth_player_name}"],
        "jvm": [
            {"rules": [{"action": "allow", "os": {"arch": "x86"}}], "value": "-Xss1M"},
            "-cp",
            "${classpath}",
        ],
    },
}


def make_version(root, vid, data):
    d = os.path.join(root, "versions", vid)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, vid + ".json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return p


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def flat_args(data):
    """Every argument string in a client.json, rules ignored."""
    out = []
    for entries in data.get("arguments", {}).values():
        for e in entries:
            if isinstance(e, str):
                out.append(e)
            elif isinstance(e, dict):
                v = e.get("value", e.get("values"))
                out.extend(v if isinstance(v, list) else [v])
    return out


# ------------------------------------------------------------------ harness ---

tmp = tempfile.mkdtemp(prefix="cubeon-clientjson-")
try:
    import cubeon.paths as paths
    paths.MINECRAFT_DIR = tmp
    import cubeon.launch as launch
    launch.MINECRAFT_DIR = tmp
    # build_launch_command() now stamps the stable identity UUID via
    # config.ensure_auth_key(); redirect that at the scratch dir so the test
    # never creates the user's real ~/.cubeon_launcher/auth_key.json.
    import cubeon.config as _config
    _config.CUBEON_HOME = tmp
    _config.AUTH_KEY_PATH = os.path.join(tmp, "auth_key.json")

    print("\n1. sanitizer repairs TLauncher's \"values\" spelling instead of deleting it")
    p = make_version(tmp, "pack", TLAUNCHER_JSON)
    launch._sanitize_client_json("pack")
    after = load(p)
    args = flat_args(after)
    check("classpath argument survived", "${classpath}" in args,
          f"args={args}")
    check("-cp survived", "-cp" in args)
    check("no entry still uses the \"values\" key",
          not any(isinstance(e, dict) and "values" in e
                  for v in after["arguments"].values() for e in v))
    check("every entry now has \"value\"",
          all("value" in e for v in after["arguments"].values()
              for e in v if isinstance(e, dict)))
    check("nothing was lost (9 args in, 9 out)", len(args) == 9, f"got {len(args)}")
    check("rules preserved on the osx entry",
          any(isinstance(e, dict) and e.get("rules") and "osx" in json.dumps(e["rules"])
              for e in after["arguments"]["jvm"]))
    check("a backup was written before rewriting",
          os.path.isfile(p + ".cubeon-backup"))
    check("backup still holds the original spelling",
          any(isinstance(e, dict) and "values" in e
              for v in load(p + ".cubeon-backup")["arguments"].values() for e in v))
    check("no temp file left behind", not os.path.exists(p + ".cubeon-tmp"))

    print("\n2. sanitizer is idempotent and leaves healthy files alone")
    p2 = make_version(tmp, "1.21.11", VANILLA_JSON)
    before_mtime = os.stat(p2).st_mtime_ns
    launch._sanitize_client_json("1.21.11")
    check("healthy file not rewritten", os.stat(p2).st_mtime_ns == before_mtime)
    check("no pointless backup for a healthy file",
          not os.path.exists(p2 + ".cubeon-backup"))
    first = load(p)
    launch._sanitize_client_json("pack")
    check("second sanitize is a no-op", load(p) == first)

    print("\n3. sanitizer refuses to save a file it would make emptier")
    # An entry with neither key is unrepairable - dropping it would lose an
    # argument, so the whole rewrite must be abandoned.
    bad = json.loads(json.dumps(VANILLA_JSON))
    bad["arguments"]["jvm"].append({"rules": [{"action": "allow"}]})
    p3 = make_version(tmp, "unrepairable", bad)
    launch._sanitize_client_json("unrepairable")
    check("file left untouched rather than emptied", load(p3) == bad)
    check("classpath still present", "${classpath}" in flat_args(load(p3)))

    print("\n4. repair rebuilds an arguments block a previous version emptied")
    p4 = make_version(tmp, "emptied", EMPTIED_JSON)
    repaired = launch._restore_emptied_arguments("emptied")
    got = load(p4)
    check("reported a repair", repaired is True)
    check("classpath restored", "${classpath}" in flat_args(got))
    check("-cp restored", "-cp" in flat_args(got))
    check("username arg restored", "--username" in flat_args(got))
    check("Fabric emulation flag added for a Knot mainClass",
          any("FabricMcEmu" in a for a in flat_args(got)))
    check("libraries untouched", got["libraries"] == EMPTIED_JSON["libraries"])
    check("mainClass untouched", got["mainClass"] == EMPTIED_JSON["mainClass"])

    print("\n5. repair prefers the backup when one exists")
    p5 = make_version(tmp, "emptied2", EMPTIED_JSON)
    with open(p5 + ".cubeon-backup", "w", encoding="utf-8") as f:
        json.dump(TLAUNCHER_JSON, f)
    launch._restore_emptied_arguments("emptied2")
    got5 = flat_args(load(p5))
    check("restored the pack's own args, not the template",
          "-DFabricMcEmu= net.minecraft.client.main.Main " in got5 and "--gameDir" not in got5,
          f"args={got5}")
    check("backup restore also normalized the key spelling",
          not any(isinstance(e, dict) and "values" in e
                  for v in load(p5)["arguments"].values() for e in v))

    print("\n6. repair is narrow - it only touches the exact damage signature")
    p6 = make_version(tmp, "healthy", VANILLA_JSON)
    check("healthy version not repaired",
          launch._restore_emptied_arguments("healthy") is False)
    check("healthy version unchanged", load(p6) == VANILLA_JSON)

    inh = {"id": "fab", "type": "release", "inheritsFrom": "1.21.11",
           "mainClass": "net.fabricmc.loader.impl.launch.knot.KnotClient",
           "libraries": [], "arguments": {"game": [], "jvm": []}}
    p6b = make_version(tmp, "inheriting", inh)
    check("an inheriting profile with empty args is left alone",
          launch._restore_emptied_arguments("inheriting") is False)
    check("inheriting profile unchanged", load(p6b) == inh)
    check("missing version is a no-op",
          launch._restore_emptied_arguments("does-not-exist") is False)

    print("\n7. the real crash: full command build on a TLauncher-shaped pack")
    # This is the end-to-end assertion. Before the fix this produced a command
    # with no -cp at all, and the game died on KnotClient.
    real = json.loads(json.dumps(TLAUNCHER_JSON))
    real["id"] = "realpack"
    real["assets"] = "29"
    real["assetIndex"] = {"id": "29"}
    real["libraries"] = [{"name": "net.fabricmc:fabric-loader:0.18.4"}]
    make_version(tmp, "realpack", real)
    os.makedirs(os.path.join(tmp, "libraries"), exist_ok=True)
    try:
        cmd = launch.build_launch_command("realpack", "tester", 2048, 854, 480, None)
        cp_idx = cmd.index("-cp") if "-cp" in cmd else -1
        check("-cp present in the built command", cp_idx != -1, f"cmd={cmd}")
        if cp_idx != -1:
            cp = cmd[cp_idx + 1]
            check("classpath was substituted, not left as a placeholder",
                  "${classpath}" not in cp and cp != "")
            check("fabric-loader is on the classpath", "fabric-loader" in cp, cp[:200])
        check("mainClass is in the command",
              "net.fabricmc.loader.impl.launch.knot.KnotClient" in cmd)
    except Exception as ex:
        check("build_launch_command did not raise", False, f"{type(ex).__name__}: {ex}")

    print("\n8. loader selection is deterministic and prefers the canonical profile")
    from cubeon.mod_loaders import find_installed_loader_version as find

    ids = {
        "fabric-loader-0.19.3-1.21.11",
        "Boosted FPS (Performance Optimized) (FB) Boosted FPS Fabric-1.21.11-1.6.7",
        "[SFP] SUPER FPS FOR POTATOES (1.21.11 Updated) [SFP] SUPER FPS FOR POTATOS 2.0.0",
        "1.21.11",
    }
    got = find(ids, "fabric", "1.21.11")
    check("picks the real Fabric profile over imported packs",
          got == "fabric-loader-0.19.3-1.21.11", f"got {got!r}")

    # The bug was order-dependence, so assert stability across many orderings.
    results = {find(set(perm), "fabric", "1.21.11")
               for perm in (list(ids), list(ids)[::-1], sorted(ids), sorted(ids, reverse=True))}
    check("same answer regardless of set ordering", len(results) == 1, f"got {results}")

    check("still finds a pack when it's the only candidate",
          find({"Some Pack Fabric-1.20.1-2.0"}, "fabric", "1.20.1")
          == "Some Pack Fabric-1.20.1-2.0")
    check("no false match for a different mc version",
          find({"fabric-loader-0.19.3-1.21.11"}, "fabric", "1.20.1") is None)
    check("forge does not match neoforge",
          find({"neoforge-21.1.99"}, "forge", "21.1") is None)
    check("neoforge matches its own profile",
          find({"neoforge-21.1.99"}, "neoforge", "21.1") == "neoforge-21.1.99")
    check("vanilla needs an exact id",
          find({"1.21.11", "fabric-loader-0.19.3-1.21.11"}, "vanilla", "1.21.11") == "1.21.11")
    check("vanilla returns None when not installed",
          find({"fabric-loader-0.19.3-1.21.11"}, "vanilla", "1.21.11") is None)

    print("\n9. against the real pristine TLauncher pack on this machine, if present")
    real_pack = os.path.expanduser(
        "~/.minecraft/versions/Boosted FPS (Performance Optimized) (FB) "
        "Boosted FPS Fabric-26.2-1.7.4/Boosted FPS (Performance Optimized) (FB) "
        "Boosted FPS Fabric-26.2-1.7.4.json"
    )
    if os.path.isfile(real_pack):
        vid = "realworld"
        d = os.path.join(tmp, "versions", vid)
        os.makedirs(d, exist_ok=True)
        target = os.path.join(d, vid + ".json")
        shutil.copy(real_pack, target)
        orig = load(target)
        orig_count = sum(len(v) for v in orig["arguments"].values() if isinstance(v, list))
        launch._sanitize_client_json(vid)
        fixed = load(target)
        new_count = sum(len(v) for v in fixed["arguments"].values() if isinstance(v, list))
        check(f"no argument entries lost ({orig_count} in)", new_count == orig_count,
              f"{orig_count} -> {new_count}")
        check("classpath survived on the real file", "${classpath}" in flat_args(fixed))
        check("pack's GC tuning survived",
              any("UseZGC" in str(a) for a in flat_args(fixed)))
        check("default_user_jvm section preserved",
              "default_user_jvm" in fixed["arguments"])
    else:
        print("  skip (pristine pack not on this machine)")

finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
