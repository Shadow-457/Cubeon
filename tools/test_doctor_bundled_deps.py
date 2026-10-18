#!/usr/bin/env python3
"""The 2026-10-18 report: "whenever I press fix problems it just disables my
sodium and some mods".

Root cause: `mod_doctor`'s `depends` pass resolved every declared dependency
id against Modrinth and, when a lookup failed, turned the DECLARING mod off as
a "the game would hard-fail anyway" last resort. But a profile provides far
more mod ids than it has jar files - Fabric API ships 43 modules inside its
own jar (fabric-rendering-fluids-v1, fabric-resource-loader-v0, ...), and
mods like c2me bundle 20+ modules of their own. None of those is a Modrinth
project, so the lookup 404'd and working mods were silently disabled: on the
reporting user's profile that was sodium, modmenu and c2me.

Locked-in behaviors:

  1. a dependency satisfied by a module BUNDLED inside an installed jar
     (META-INF/jars/*.jar) is satisfied - no problem, no toggle
  2. that holds for the whole real-world shape: fabric-api + sodium + modmenu
     + a self-bundling mod (c2me), with every network lookup failing
  3. a bundled module only satisfies a version predicate it actually meets
  4. the highest bundled version wins when several jars ship the same module
  5. a genuinely missing dependency is reported, never auto-disabled
  6. ...even when it cannot be fetched at all (offline / 404 / rate limit)
  7. a missing dependency that CAN be fetched is still installed (the repair
     this pass exists for is unchanged)
  8. `_nested_mod_metadata` never raises on a broken jar
"""
import io
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home  # noqa: E402

_sandbox_home.isolate()

import cubeon.mods as mods  # noqa: E402

_passed = _failed = 0


def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok  {label}")
    else:
        _failed += 1
        print(f"FAIL  {label}  {detail}")


MC = "26.1.2"
LOADER = "fabric"
PROFILE = mods.get_profile_dir(MC, LOADER)


# --- jar builders ----------------------------------------------------------
def fabric_jar_bytes(mod_id, version, *, depends=None, breaks=None,
                     nested=None):
    """A Fabric jar: fabric.mod.json plus optional jar-in-jar children, which
    is exactly how Fabric API ships its 43 modules."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("fabric.mod.json", json.dumps({
            "id": mod_id, "version": version, "name": mod_id,
            "depends": depends or {}, "breaks": breaks or {},
        }))
        for child in nested or []:
            cbuf = io.BytesIO()
            with zipfile.ZipFile(cbuf, "w") as cz:
                cz.writestr("fabric.mod.json", json.dumps(child))
            z.writestr(f"META-INF/jars/{child['id']}-{child['version']}.jar",
                       cbuf.getvalue())
    return buf.getvalue()


def write_mod(filename, *a, **kw):
    os.makedirs(PROFILE, exist_ok=True)
    with open(os.path.join(PROFILE, filename), "wb") as fh:
        fh.write(fabric_jar_bytes(*a, **kw))


def reset_profile():
    if os.path.isdir(PROFILE):
        for name in os.listdir(PROFILE):
            try:
                os.remove(os.path.join(PROFILE, name))
            except OSError:
                pass


def dead_network(*_a, **_k):
    """Every lookup fails, the way an offline / rate-limited / 404'd pass does
    for an id that is not a Modrinth project."""
    raise RuntimeError("simulated 404")


def run_doctor(**kw):
    """The doctor with toggles recorded instead of performed."""
    toggled = []
    real_toggle = mods.toggle_mod
    mods.toggle_mod = lambda mc, ld, fn: toggled.append(fn)
    try:
        rep = mods.mod_doctor(MC, LOADER, auto_fix=True, check_online=True, **kw)
    finally:
        mods.toggle_mod = real_toggle
    return rep, toggled


def prob(rep, key):
    """Problems naming a mod - the doctor reports DISPLAY names (the file stem
    for an unsourced jar), so match on a normalized substring rather than the
    raw mod id."""
    def norm(s):
        return "".join(c for c in str(s).lower() if c.isalnum())
    want = norm(key)
    return [x for x in rep["problems"] if want in norm(x.get("mod", ""))]


print("1. _nested_mod_metadata reads jar-in-jar modules")
reset_profile()
write_mod("fabric-api-0.150.0.jar", "fabric-api", "0.150.0+26.1.2",
          nested=[{"id": "fabric-rendering-fluids-v1",
                   "version": "6.0.1+d871b99e4c"},
                  {"id": "fabric-resource-loader-v0",
                   "version": "3.3.17+4fc5413f4c"},
                  {"id": "fabric-api-base", "version": "2.0.3+ece063234c"}])
prov = mods._nested_mod_metadata(
    os.path.join(PROFILE, "fabric-api-0.150.0.jar"))
check("the jar's own id is indexed", prov.get("fabric-api") == "0.150.0+26.1.2",
      str(prov))
check("a bundled module is indexed",
      prov.get("fabric-rendering-fluids-v1") == "6.0.1+d871b99e4c", str(prov))
check("all three bundled modules are indexed", len(prov) == 4, str(prov))
check("a broken jar contributes nothing and never raises",
      mods._nested_mod_metadata(os.path.join(PROFILE, "nope-does-not-exist.jar"))
      == {})

print("\n2. the reported profile: nothing gets disabled")
# The real shape: sodium depends on Fabric API submodules, modmenu on four
# more, c2me on a module it bundles ITSELF. Before the fix all three were
# turned off, every single time Fix problems ran.
reset_profile()
write_mod("fabric-api-0.150.0.jar", "fabric-api", "0.150.0+26.1.2",
          nested=[{"id": i, "version": v} for i, v in (
              ("fabric-block-getter-api-v2", "2.0.6+ec56b6014c"),
              ("fabric-rendering-fluids-v1", "6.0.1+d871b99e4c"),
              ("fabric-resource-loader-v0", "3.3.17+4fc5413f4c"),
              ("fabric-resource-loader-v1", "2.0.10+7c44c7324c"),
              ("fabric-screen-api-v1", "5.0.1+d871b99e4c"),
              ("fabric-key-mapping-api-v1", "2.0.4+e2bdee784c"),
              ("fabric-lifecycle-events-v1", "4.1.0+6d50a0854c"),
          )])
write_mod("sodium-0.8.12.jar", "sodium", "0.8.12+mc26.1.2", depends={
    "fabricloader": ">=0.16.0",
    "fabric-block-getter-api-v2": "*",
    "fabric-rendering-fluids-v1": ">=2.0.0",
    "fabric-resource-loader-v0": "*",
})
write_mod("modmenu-18.jar", "modmenu", "18.0.0", depends={
    "fabric-resource-loader-v1": "*", "fabric-screen-api-v1": "*",
    "fabric-key-mapping-api-v1": "*", "fabric-lifecycle-events-v1": "*",
})
write_mod("c2me-0.3.7.jar", "c2me", "0.3.7", depends={"c2me-base": "*"},
          nested=[{"id": "c2me-base", "version": "0.3.7+26.1.2"}])

_orig_dl = mods.get_mod_download
mods.get_mod_download = dead_network
mods._required_deps_cached = lambda *a, **k: []
try:
    rep, toggled = run_doctor()
finally:
    mods.get_mod_download = _orig_dl

check("no mod is disabled", not toggled, str(toggled))
check("sodium is not reported as broken", not prob(rep, "sodium"),
      str(rep["problems"]))
check("modmenu is not reported as broken", not prob(rep, "modmenu"),
      str(rep["problems"]))
check("c2me is not reported as broken (it bundles its own dep)",
      not prob(rep, "c2me"), str(rep["problems"]))
check("all three are counted as checked", rep["checked"] == 4, str(rep["checked"]))

print("\n3. the predicate is still honoured for bundled modules")
reset_profile()
write_mod("fabric-api-0.150.0.jar", "fabric-api", "0.150.0", nested=[
    {"id": "fabric-rendering-fluids-v1", "version": "1.0.0+aaaa"}])
write_mod("needs-newer-fluids.jar", "needsnewer", "1.0", depends={
    "fabric-rendering-fluids-v1": ">=2.0.0"})
rep, toggled = run_doctor()
_probs = prob(rep, "needsnewer")
check("a bundled module older than the predicate is reported",
      len(_probs) == 1 and "bundled copy" in _probs[0]["detail"], str(_probs))
check("...and the mod is still NOT disabled", not toggled, str(toggled))

print("\n4. the highest bundled version wins")
reset_profile()
write_mod("a-old-mod.jar", "oldmod", "1.0", nested=[
    {"id": "shared-module", "version": "1.0.0"}])
write_mod("b-new-mod.jar", "newmod", "1.0", nested=[
    {"id": "shared-module", "version": "2.5.0"}])
write_mod("wants-two.jar", "wantstwo", "1.0", depends={"shared-module": ">=2.0"})
rep, toggled = run_doctor()
check("a predicate met by the NEWER bundled copy is satisfied",
      not prob(rep, "wantstwo"), str(rep["problems"]))

print("\n5. a genuinely missing dependency is reported, never disabled")
reset_profile()
write_mod("wurst-7.55.jar", "wurst", "7.55", depends={"baritone-api": "*"})
rep, toggled = run_doctor()
_probs = prob(rep, "wurst")
check("the missing dependency is reported", len(_probs) == 1, str(rep["problems"]))
check("...as unfixed", _probs and _probs[0]["fixed"] is False, str(_probs))
check("...and the mod is left ENABLED (the reported bug)", not toggled,
      str(toggled))
check("...with wording that says it could not be fetched",
      _probs and "couldn't be fetched" in _probs[0]["detail"], str(_probs))

print("\n6. a missing dependency that CAN be fetched is still installed")
reset_profile()
write_mod("moreculling-1.0.jar", "moreculling", "1.0",
          depends={"cloth-config": "*"})
_installed = []


def _fake_download(*a, **k):
    raise RuntimeError("simulated 404")


def _fake_dep_lookup(ref, mc_version=None, loader=None):
    if str(ref) == "cloth-config":
        return {"filename": "cloth-config-26.1.154.jar",
                "url": "https://cdn/cloth-config.jar",
                "version_number": "26.1.154", "hashes": {}}
    raise RuntimeError("no route")


_orig_lookup = mods.get_mod_download
_orig_download = mods.download_mod


def _fake_download_mod(url, filename, **kw):
    _installed.append(filename)


mods.get_mod_download = _fake_dep_lookup
mods.download_mod = _fake_download_mod
mods._required_deps_cached = lambda *a, **k: []
try:
    rep, toggled = run_doctor()
finally:
    mods.get_mod_download = _orig_lookup
    mods.download_mod = _orig_download
_probs = prob(rep, "moreculling")
check("the fetchable dependency is installed instead of disabling the mod",
      _probs and _probs[0]["fixed"] and "installed" in _probs[0].get("fix", ""),
      str(_probs))
check("...the right jar was requested",
      _installed == ["cloth-config-26.1.154.jar"], str(_installed))
check("...and nothing was turned off", not toggled, str(toggled))

print(f"\n{_passed} passed, {_failed} failed")
print("Doctor bundled-deps test: " + ("PASS" if not _failed else "FAIL"))
sys.exit(1 if _failed else 0)
