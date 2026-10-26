"""
Offline test for the "a pack install is still writing this instance" guard.

Report (2026-10-18): while a modpack install was still downloading its mods,
the Play tab already offered PLAY for that instance (the base version + loader
land on disk first, so a disk scan calls it installed), and pressing it
launched a half-written profile - "that will result in broken stuff".

What is exercised here:
  * cubeon/modpacks.py's in-flight registry: raised for the WHOLE install
    (before the first byte is written), cleared on success, on failure and on
    cancel, refcounted when two installs overlap on one version, and
    read-only snapshots never hand out a live dict.
  * the listener seam the Play button hangs off: fires on start and end, and a
    broken listener can neither break the install nor mute its siblings.
  * main.py's wiring: the button derives its disabled "INSTALLING..." state
    from that registry (not from a UI flag), the click path refuses, and the
    prefetch and the mod doctor stand down while a pack owns the instance.

No network, no display, no real Minecraft install: install_version /
install_mod_loader / get_profile_dir are stubbed and MINECRAFT_DIR is
redirected into a scratch tempdir.
"""
import json
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# --- sandbox: redirect HOME to a scratch dir before cubeon binds its paths at
# import time, so tests never read/write the developer's real game dir/store.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home
_sandbox_home.isolate()

from cubeon import modpacks

_passed = _failed = 0


def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok  {label}")
    else:
        _failed += 1
        print(f"FAIL  {label}  {detail}")


def _minimal_mrpack(path, *, mc="1.20.1", name="Guard Pack", loader="fabric"):
    """A valid pack that declares a version + loader and NO files, so the
    install touches no network at all."""
    index = {
        "formatVersion": 1,
        "game": "minecraft",
        "versionId": "1.0.0",
        "name": name,
        "dependencies": {"minecraft": mc},
        "files": [],
    }
    if loader:
        index["dependencies"][f"{loader}-loader"] = "0.15.7"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("modrinth.index.json", json.dumps(index))


def main():
    scratch = tempfile.mkdtemp(prefix="cubeon-packguard-")
    game_dir = os.path.join(scratch, "minecraft")
    profile_dir = os.path.join(scratch, "profile")
    os.makedirs(game_dir)
    os.makedirs(profile_dir)

    modpacks.MINECRAFT_DIR = game_dir
    modpacks.install_version = lambda *a, **k: None
    modpacks.install_mod_loader = lambda lid, mc, *a, **k: f"{lid}-loader-{mc}"
    modpacks.get_profile_dir = lambda mc, loader, version_id=None: profile_dir

    pack = os.path.join(scratch, "guard.mrpack")
    _minimal_mrpack(pack)

    # --- identity peek -----------------------------------------------------
    mc, name = modpacks._peek_pack_identity(pack)
    check("peek: reads the real mc_version + name",
          (mc, name) == ("1.20.1", "Guard Pack"), f"{mc!r}/{name!r}")
    junk = os.path.join(scratch, "notes.txt")
    with open(junk, "w") as fh:
        fh.write("not a pack")
    check("peek: unreadable archive yields ('', ''), never raises",
          modpacks._peek_pack_identity(junk) == ("", ""),
          str(modpacks._peek_pack_identity(junk)))
    check("peek: a missing file also yields ('', '')",
          modpacks._peek_pack_identity(os.path.join(scratch, "gone.mrpack"))
          == ("", ""))

    # --- the claim covers the whole install --------------------------------
    check("clean start: nothing is claimed",
          modpacks.pack_install_for("1.20.1") is None
          and modpacks.active_pack_installs() == {},
          str(modpacks.active_pack_installs()))

    seen_during = []

    def status_cb(text):
        # Every status the install emits must see the claim - the first one is
        # "Installing Minecraft 1.20.1", i.e. before any game-file write.
        seen_during.append(modpacks.pack_install_for("1.20.1"))

    meta = modpacks.install_modpack_from_file(pack, status_cb=status_cb)
    check("install: the pack still reports its own meta",
          meta.get("mc_version") == "1.20.1" and meta.get("loader") == "fabric",
          str(meta))
    check("install: the claim is held for EVERY status the install emits",
          bool(seen_during) and all(seen_during),
          str(seen_during))
    check("install: the claim is released when the install returns",
          modpacks.pack_install_for("1.20.1") is None
          and modpacks.active_pack_installs() == {},
          str(modpacks.active_pack_installs()))

    # --- listeners fire on both edges --------------------------------------
    events = []

    def listener():
        events.append(modpacks.pack_install_for("1.20.1"))

    modpacks.add_pack_install_listener(listener)
    modpacks.add_pack_install_listener(listener)  # idempotent
    modpacks.install_modpack_from_file(pack)
    check("listener: fires once on start (claim up) and once on end (clear)",
          events == ["Guard Pack", None], str(events))

    # A broken listener must not break the install or mute its siblings.
    after = []

    def bad_listener():
        raise RuntimeError("boom")

    modpacks.add_pack_install_listener(bad_listener)
    modpacks.add_pack_install_listener(lambda: after.append(1))
    meta2 = modpacks.install_modpack_from_file(pack)
    check("listener: a raising listener can't fail the install",
          meta2.get("mc_version") == "1.20.1", str(meta2))
    check("listener: a raising listener doesn't mute the others",
          len(after) == 2, str(after))
    modpacks._INSTALL_LISTENERS.remove(bad_listener)

    # --- failure and cancel both release the claim -------------------------
    def boom(*a, **k):
        raise RuntimeError("net death")

    real_install_version = modpacks.install_version
    modpacks.install_version = boom
    try:
        modpacks.install_modpack_from_file(pack)
        check("failure: the install error propagates", False, "no exception")
    except RuntimeError:
        check("failure: the install error propagates", True)
    finally:
        modpacks.install_version = real_install_version
    check("failure: no claim is left behind",
          modpacks.pack_install_for("1.20.1") is None,
          str(modpacks.active_pack_installs()))

    class _Abort(Exception):
        pass

    def cancel_cb(text):
        if "Installing Minecraft" in text:
            raise _Abort("cancelled")

    try:
        modpacks.install_modpack_from_file(pack, status_cb=cancel_cb)
        check("cancel: the abort propagates", False, "no exception")
    except _Abort:
        check("cancel: the abort propagates", True)
    check("cancel: no claim is left behind",
          modpacks.pack_install_for("1.20.1") is None,
          str(modpacks.active_pack_installs()))

    # --- overlapping installs of one version stay claimed until the last ---
    real_body = modpacks._install_from_zip_body
    calls = {"n": 0}

    def reentrant_body(zip_path, *, progress_cb=None, status_cb=None,
                       max_cb=None, icon_url=None):
        calls["n"] += 1
        if calls["n"] == 1:
            # A second install of the SAME version starts while this one runs
            # (a reinstall racing an import). The claim must survive the first
            # one finishing.
            modpacks._install_from_zip(zip_path)
        return {"mc_version": "1.20.1", "name": "Guard Pack"}

    modpacks._install_from_zip_body = reentrant_body
    try:
        modpacks._install_from_zip(pack)
        check("overlap: the inner install ran",
              calls["n"] == 2, str(calls))
    finally:
        modpacks._install_from_zip_body = real_body
    check("overlap: the claim is cleared only after the LAST install",
          modpacks.pack_install_for("1.20.1") is None,
          str(modpacks.active_pack_installs()))

    # --- a non-pack file claims nothing ------------------------------------
    try:
        modpacks._install_from_zip(junk)
        check("junk: raises rather than silently claiming", False)
    except modpacks.ModpackError:
        check("junk: raises rather than silently claiming", True)
    check("junk: leaves no claim behind",
          modpacks.active_pack_installs() == {},
          str(modpacks.active_pack_installs()))

    # --- snapshots are copies ----------------------------------------------
    modpacks._mark_pack_install("1.21", "Other Pack")
    try:
        snap = modpacks.active_pack_installs()
        snap["1.21"] = "tampered"
        check("snapshot: callers can't mutate the registry",
              modpacks.active_pack_installs().get("1.21") == "Other Pack",
              str(modpacks.active_pack_installs()))
        check("snapshot: keyed by mc_version, valued by pack name",
              modpacks.pack_install_for("1.21") == "Other Pack")
    finally:
        modpacks._unmark_pack_install("1.21")

    # --- main.py wiring ----------------------------------------------------
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "main.py"), encoding="utf-8") as fh:
        main_src = fh.read()

    check("button: a pack install maps to a disabled INSTALLING state",
          'elif _pack_installing_selected():' in main_src
          and 'mode = "installing"' in main_src
          and 'play_button_text.value = "INSTALLING..."' in main_src,
          "the Play button must read the registry, not a UI flag")
    check("button: the disabled state is not a lying CANCEL",
          'mode == "installing"' in main_src
          and 'tooltip = ("Cubeon is still installing' in main_src,
          "the Modpacks tab owns that install and its cancel")
    check("click: on_play_click refuses a version a pack is writing",
          "core.pack_install_for(\n                core.extract_mc_version(version_id))"
          in main_src,
          "PLAY must not launch a half-installed profile")
    check("click: the Java-prompt entry point is guarded too",
          "core.pack_install_for(\n                    core.extract_mc_version(version_id))"
          in main_src,
          "_begin_install_and_launch is reached directly from the Java dialog")
    check("selection starts no hidden download that could race a pack install",
          "prefetch_version(" not in main_src,
          "downloads start only through the explicit main action")
    check("doctor: skips a profile a pack is still writing",
          "if core.pack_install_for(mc):" in main_src
          and "Skip WITHOUT" in main_src,
          "auto_fix could prune jars whose downloads are still in flight")
    check("wiring: the button repaints when the claim changes",
          "core.add_pack_install_listener(_sync_play_button)" in main_src,
          "otherwise INSTALLING... outlives a cancel or lingers after success")
    _play_branch = main_src.split('elif key == "play":', 1)[-1].split(
        "except Exception", 1)[0]
    check("wiring: Play-tab entry re-derives the button",
          "_reconcile_running_button()" in _play_branch
          and "_sync_play_button()" in _play_branch,
          "a claim made while the Play tab was hidden must be visible on return")

    print(f"\n{_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
