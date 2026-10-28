"""Enabling/disabling a mod must never overwrite the other state (9.3).

If `x.jar` and `x.jar.disabled` both exist (a re-download while the old copy is
disabled), `toggle_mod` used to `os.rename` onto the existing file: silent data
loss on Linux/macOS, an uncaught `FileExistsError` inside a click handler on
Windows.

Run: python tools/test_mod_toggle_collision.py
"""
import os
import sys

sys.path[:0] = [os.path.dirname(__file__),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
import _sandbox_home

_sandbox_home.isolate()

from cubeon import mods  # noqa: E402

passed = failed = 0


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


def main():
    mc, loader = "1.20.1", "fabric"
    profile = mods.get_profile_dir(mc, loader)
    jar = os.path.join(profile, "sodium.jar")
    disabled = jar + ".disabled"
    with open(jar, "wb") as fh:
        fh.write(b"ENABLED BYTES")
    with open(disabled, "wb") as fh:
        fh.write(b"DISABLED BYTES")

    raised = None
    try:
        mods.toggle_mod(mc, loader, "sodium.jar")
    except Exception as ex:
        raised = ex
    check("a collision is refused, not carried out",
          isinstance(raised, ValueError), repr(raised))
    check("the message says what to do",
          raised is not None and "delete one first" in str(raised),
          str(raised))
    with open(jar, "rb") as fh:
        check("the enabled copy is untouched", fh.read() == b"ENABLED BYTES")
    with open(disabled, "rb") as fh:
        check("the disabled copy is untouched", fh.read() == b"DISABLED BYTES")

    # The normal direction still works: enabled -> disabled.
    os.remove(disabled)
    mods.toggle_mod(mc, loader, "sodium.jar")
    check("a normal disable still renames",
          not os.path.exists(jar) and os.path.isfile(disabled))
    # ...and disabled -> enabled.
    mods.toggle_mod(mc, loader, "sodium.jar.disabled")
    check("a normal enable still renames",
          os.path.isfile(jar) and not os.path.exists(disabled))

    print()
    print(f"{passed} passed, {failed} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
