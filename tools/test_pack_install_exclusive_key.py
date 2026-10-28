"""The in-flight pack claim is scoped per (Minecraft version, loader) (8.4).

`_ACTIVE_INSTALLS` was keyed by `mc_version` alone, so while any pack installed
for 1.20.1 a second pack for the same base version was refused even when it
targeted another loader and wrote a different loader folder.

The Play button was already instance-scoped (`pack_install_for_instance`); this
item fixes the remaining exclusivity key:

  * (mc, loader) may be claimed once; a second claim for the same pair is
    refused with a readable `ModpackError`;
  * a different loader for the same MC version is a different claim;
  * a legacy caller that does not pass a loader still collides with every claim
    for that base version (it cannot prove it is different);
  * `pack_install_for(mc)` / `active_pack_installs()` keep their MC-only view.

Run: python tools/test_pack_install_exclusive_key.py
"""
import os
import sys

sys.path[:0] = [os.path.dirname(__file__),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
import _sandbox_home

_sandbox_home.isolate()

from cubeon import modpacks  # noqa: E402

passed = failed = 0

MC = "1.20.1"


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


def error_of(fn):
    try:
        fn()
    except Exception as ex:
        return ex
    return None


def main():
    with modpacks._ACTIVE_INSTALLS_LOCK:
        modpacks._ACTIVE_INSTALLS.clear()

    # --- 1. different loaders coexist -------------------------------------
    modpacks._mark_pack_install(MC, "Fabric Pack", loader="fabric",
                                exclusive=True)
    ex = error_of(lambda: modpacks._mark_pack_install(
        MC, "Forge Pack", loader="forge", exclusive=True))
    check("a second loader for the same MC version is allowed",
          ex is None, repr(ex))
    check("the base-version view still reports a running install",
          modpacks.pack_install_for(MC) in ("Fabric Pack", "Forge Pack"),
          str(modpacks.pack_install_for(MC)))
    check("active_pack_installs() keeps its MC-only key",
          list(modpacks.active_pack_installs()) == [MC],
          str(modpacks.active_pack_installs()))

    # --- 2. the same pair is still exclusive ------------------------------
    ex = error_of(lambda: modpacks._mark_pack_install(
        MC, "Another Fabric Pack", loader="fabric", exclusive=True))
    check("a second pack for the same MC + loader is refused",
          isinstance(ex, modpacks.ModpackError), repr(ex))
    check("the refusal explains what is running",
          isinstance(ex, modpacks.ModpackError)
          and "Minecraft version and loader" in str(ex), repr(ex))

    # --- 3. releasing one loader leaves the other -------------------------
    modpacks._unmark_pack_install(MC, "fabric")
    check("the other loader's claim survives",
          modpacks.pack_install_for(MC) == "Forge Pack",
          str(modpacks.pack_install_for(MC)))
    modpacks._unmark_pack_install(MC, "forge")
    check("all claims are gone",
          modpacks.pack_install_for(MC) is None
          and modpacks.active_pack_installs() == {},
          str(modpacks.active_pack_installs()))

    # --- 4. legacy no-loader calls keep the old collision rule ------------
    modpacks._mark_pack_install(MC, "Legacy Pack", exclusive=True)
    ex = error_of(lambda: modpacks._mark_pack_install(
        MC, "Fabric Pack", loader="fabric", exclusive=True))
    check("a legacy claim blocks a known-loader claim for the same MC",
          isinstance(ex, modpacks.ModpackError), repr(ex))
    modpacks._unmark_pack_install(MC)
    check("the legacy claim is released by an unkeyed unmark",
          modpacks.active_pack_installs() == {},
          str(modpacks.active_pack_installs()))

    ex = error_of(lambda: modpacks._mark_pack_install(
        MC, "Fabric Pack", loader="fabric", exclusive=True))
    check("no stale claim survives into a fresh install", ex is None, repr(ex))
    modpacks._unmark_pack_install(MC, "fabric")

    # --- 5. a different MC version never collides -------------------------
    modpacks._mark_pack_install(MC, "Fabric Pack", loader="fabric",
                                exclusive=True)
    ex = error_of(lambda: modpacks._mark_pack_install(
        "26.3", "New Pack", loader="fabric", exclusive=True))
    check("another Minecraft version installs independently", ex is None,
          repr(ex))
    modpacks._unmark_pack_install(MC, "fabric")
    modpacks._unmark_pack_install("26.3", "fabric")
    check("the registry is empty at the end",
          modpacks.active_pack_installs() == {},
          str(modpacks.active_pack_installs()))

    print()
    print(f"{passed} passed, {failed} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
