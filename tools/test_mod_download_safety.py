"""API-supplied mod filenames are sanitized and URLs host-checked (9.7).

`download_mod` joined `filename` straight from Modrinth/CurseForge metadata or
a pack's dependency list onto the profile dir, and fetched `download_url`
without a host check - unlike the modpack installer, which only fetches from
the mrpack allowlist. A `../..` name escaped the profile folder, a `.exe` was
written next to the game, and a bad URL was fetched from anywhere.

Locked-in behaviour:
  * the filename is reduced to its basename and sanitized (`_safe_jar_filename`);
    Windows separators are normalized first, so `..\\..\\x.jar` cannot escape;
  * a non-`.jar` name is refused;
  * `download_mod` refuses a URL whose host is not on `modpacks._host_allowed`
    (https Modrinth/GitHub/GitLab/CurseForge CDN), before any network work;
  * `install_mod_with_dependencies` sanitizes its own filename before resolving
    dependencies, and sanitizes each dependency's filename; a bad dependency is
    reported in `failed`, never raised.

Run: python tools/test_mod_download_safety.py
"""
import os
import sys
from unittest.mock import patch

sys.path[:0] = [os.path.dirname(__file__),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
import _sandbox_home

_sandbox_home.isolate()

from cubeon import mods  # noqa: E402

passed = failed = 0

MC, LOADER = "1.20.1", "fabric"
GOOD_URL = "https://cdn.modrinth.com/data/AANobbMI/versions/abc/main.jar"


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


def fake_fetch(dest, fetch_fn, hashes):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as fh:
        fh.write(b"jar")


def main():
    profile = mods.get_profile_dir(MC, LOADER)
    os.makedirs(profile, exist_ok=True)
    scratch = os.path.dirname(profile)

    # --- 1. the filename helper itself -------------------------------------
    check("a plain name is unchanged",
          mods._safe_download_filename("sodium-0.5.0.jar") == "sodium-0.5.0.jar")
    check("a POSIX traversal is reduced to the basename",
          mods._safe_download_filename("../../evil.jar") == "evil.jar",
          mods._safe_download_filename("../../evil.jar"))
    check("a Windows traversal is reduced to the basename",
          mods._safe_download_filename("..\\..\\evil.jar") == "evil.jar",
          mods._safe_download_filename("..\\..\\evil.jar"))
    check("illegal characters are replaced",
          mods._safe_download_filename('bad:name?.jar') == "bad_name_.jar",
          mods._safe_download_filename('bad:name?.jar'))
    check("an absolute path is reduced to the basename",
          mods._safe_download_filename("/etc/evil.jar") == "evil.jar",
          mods._safe_download_filename("/etc/evil.jar"))
    for bad in ("evil.exe", "evil.jar.exe", "evil.zip"):
        check(f"{bad} is refused",
              isinstance(error_of(lambda: mods._safe_download_filename(bad)),
                         ValueError))
    check("an empty name is refused",
          isinstance(error_of(lambda: mods._safe_download_filename("")),
                     ValueError))

    # --- 2. download_mod refuses a non-jar before touching the network -----
    with patch.object(mods.global_mod_cache, "get_or_fetch", fake_fetch):
        ex = error_of(lambda: mods.download_mod(
            GOOD_URL, "evil.exe", mc_version=MC, loader=LOADER))
    check("download_mod refuses a non-jar", isinstance(ex, ValueError), repr(ex))

    # --- 3. download_mod refuses an untrusted host -------------------------
    fetched = []
    with patch.object(mods.global_mod_cache, "get_or_fetch",
                      lambda *a, **k: fetched.append(a[0])):
        for label, url in (("an unknown host", "https://evil.example.com/x.jar"),
                           ("a plain-http URL", "http://cdn.modrinth.com/x.jar")):
            ex = error_of(lambda u=url: mods.download_mod(
                u, "x.jar", mc_version=MC, loader=LOADER))
            check(f"download_mod refuses {label}", isinstance(ex, ValueError),
                  repr(ex))
    check("nothing was fetched for a refused URL", not fetched, str(fetched))

    # --- 4. an allowlisted download still works, inside the profile --------
    with patch.object(mods.global_mod_cache, "get_or_fetch", fake_fetch):
        result = mods.download_mod(
            GOOD_URL, "../../escape.jar",
            mc_version=MC, loader=LOADER)
    check("a traversal name lands as a plain file in the profile",
          os.path.dirname(result) == profile
          and os.path.basename(result) == "escape.jar", result)
    check("the write stayed inside the profile",
          os.path.isfile(os.path.join(profile, "escape.jar"))
          and not os.path.exists(os.path.join(scratch, "escape.jar")),
          result)

    # --- 5. install_mod_with_dependencies sanitizes before resolving ------
    calls = []

    def spy_deps(*a, **k):
        calls.append(("deps", a, k))
        return []

    with patch.object(mods, "required_dependencies", spy_deps), \
            patch.object(mods, "download_mod",
                         lambda *a, **k: calls.append(("download", a, k))):
        ex = error_of(lambda: mods.install_mod_with_dependencies(
            GOOD_URL, "../../main.exe", MC, LOADER, project_id="main-id"))
    check("the main filename is refused", isinstance(ex, ValueError), repr(ex))
    check("a bad main filename is refused before dependencies are resolved",
          not calls, str(calls))

    # --- 6. dependencies are sanitized and a bad one only fails ------------
    deps = [
        {"project_id": "dep-ok", "filename": "../../dep-ok.jar",
         "url": "https://cdn.modrinth.com/data/d1/versions/x/dep-ok.jar"},
        {"project_id": "dep-exe", "filename": "dep-exe.exe",
         "url": "https://cdn.modrinth.com/data/d2/versions/x/dep-exe.jar"},
    ]
    with patch.object(mods, "required_dependencies", lambda *a, **k: [dict(d) for d in deps]), \
            patch.object(mods.global_mod_cache, "get_or_fetch", fake_fetch):
        result = mods.install_mod_with_dependencies(
            GOOD_URL, "main.jar", MC, LOADER, slug="main", project_id="main-id")
    check("the main mod and the valid dependency are installed",
          result["installed"] == ["main.jar", "dep-ok.jar"], str(result))
    check("the dependency name was sanitized on disk",
          os.path.isfile(os.path.join(profile, "dep-ok.jar"))
          and not os.path.exists(os.path.join(scratch, "dep-ok.jar")),
          str(result))
    check("the non-jar dependency is reported as failed",
          result["failed"] == ["dep-exe.exe"], str(result))

    # --- 7. a dependency URL is host-checked by the real download ----------
    deps = [
        {"project_id": "dep-evil", "filename": "dep-evil.jar",
         "url": "https://evil.example.com/dep-evil.jar"},
        {"project_id": "dep-two", "filename": "dep-two.jar",
         "url": "https://cdn.modrinth.com/data/d3/versions/x/dep-two.jar"},
    ]
    with patch.object(mods, "required_dependencies", lambda *a, **k: [dict(d) for d in deps]), \
            patch.object(mods.global_mod_cache, "get_or_fetch", fake_fetch):
        result = mods.install_mod_with_dependencies(
            GOOD_URL, "main.jar", MC, LOADER, slug="main", project_id="main-id")
    check("an untrusted dependency host does not abort the install",
          result["installed"] == ["main.jar", "dep-two.jar"], str(result))
    check("the untrusted dependency is reported as failed",
          result["failed"] == ["dep-evil"], str(result))
    check("no file from the untrusted host was written",
          not os.path.exists(os.path.join(profile, "dep-evil.jar")))

    print()
    print(f"{passed} passed, {failed} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
