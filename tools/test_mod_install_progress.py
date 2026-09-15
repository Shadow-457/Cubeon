"""
Offline regression suite for install progress aggregation in cubeon/mods.py:
install_mod_with_dependencies().

Why this suite exists: one click that installs a mod with required
dependencies (Sodium -> Fabric API) is several downloads behind a single
button, and progress used to be reported per file - so the percent restarted
at 0 for every dependency and the UI read 100% -> 0% -> 100%. That looks
broken or hung, and is exactly how it got reported ("the 1-100% doesn't work
quite good when installing multiple mods/etc").

The contract these tests pin:
  * progress_cb is called in FILE UNITS across the whole batch (whole files
    finished + the current file's fraction), so the reported percent never
    moves backwards and a successful batch finishes at exactly 100%;
  * the batch total is FINAL before the first byte of the first file moves -
    a total discovered only after the main download forces a mid-flight
    rescale, which is the backwards jump this suite guards;
  * dependencies already installed are skipped, not re-downloaded, and don't
    inflate the total;
  * the main mod's own id can never come back as a dependency (no self-loop);
  * a dependency that fails to resolve is reported in the result, never
    raised into the click handler.

No network, no display: HOME is sandboxed (tools/_sandbox_home.py) and every
download / metadata / profile-listing call is faked at the cubeon.mods layer.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home  # noqa: E402
_sandbox_home.isolate()

import cubeon.mods as mods  # noqa: E402

MC, LOADER = "1.20.1", "fabric"
MAIN_URL = "https://cdn.modrinth.com/data/sodium-id/versions/v/sodium-0.9.2.jar"
MAIN_FILE = "sodium-fabric-0.9.2.jar"
API_FILE = "fabric-api-0.92.0.jar"
CLOTH_FILE = "cloth-config-11.0.0.jar"

_passed = _failed = 0


def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok  {label}")
    else:
        _failed += 1
        print(f"FAIL  {label}  {detail}")


# --- fakes -----------------------------------------------------------------

LOG = {"downloads": [], "dep_refs": [], "progress": [], "status": []}
FAIL_URLS = set()


def _fake_download(url, filename, **kw):
    """Stand-in transfer: reports 0%, ~33% and 100% of THAT file, like a real
    three-chunk stream, and records every call."""
    LOG["downloads"].append((url, filename))
    if url in FAIL_URLS:
        raise RuntimeError("simulated transfer failure")
    cb = kw.get("progress_cb")
    if cb:
        for done in (0, 33, 100):
            cb(done, 100)
    return os.path.join("fake-profile", filename)


def _dep(project_id, filename):
    """A dependency entry shaped exactly like required_dependencies() returns."""
    return {"project_id": project_id, "filename": filename,
            "url": f"https://cdn.modrinth.com/data/{project_id}/versions/v/{filename}",
            "size_kb": 512, "hashes": {"sha1": "0" * 40}}


def _monotonic(values):
    return all(b >= a for a, b in zip(values, values[1:]))


def run_install(*, deps=None, installed=(), fail=(), meta_project=None,
                slug="sodium", project_id="sodium-id", filename=MAIN_FILE):
    """One install with everything stubbed. Returns (result, percents)."""
    LOG["downloads"].clear()
    LOG["dep_refs"].clear()
    LOG["progress"].clear()
    LOG["status"].clear()
    FAIL_URLS.clear()
    FAIL_URLS.update(fail)

    mods.download_mod = _fake_download

    def _fake_required_deps(ref, mc_version=None, loader="fabric"):
        LOG["dep_refs"].append(ref)
        return list(deps or [])

    mods.required_dependencies = _fake_required_deps
    mods.installed_project_ids = lambda mc_version=None, loader=None: set(installed)

    if meta_project:
        # The sidecar download_mod would normally have written, so the install
        # has to resolve the project id from disk (the drag-drop case).
        mods.record_mod_source(mods.get_profile_dir(MC, LOADER), filename,
                               slug=slug, project_id=meta_project)

    result = mods.install_mod_with_dependencies(
        MAIN_URL, filename, mc_version=MC, loader=LOADER,
        slug=slug, project_id=project_id,
        progress_cb=lambda v, t: LOG["progress"].append((v, t)),
        status_cb=lambda t: LOG["status"].append(t),
    )
    percents = [int(v * 100 / t) if t else 0 for v, t in LOG["progress"]]
    return result, percents


# ---------------------------------------------------------------------------
print("\n1. a mod with no dependencies: one clean climb, no rescale")
# ---------------------------------------------------------------------------
result, percents = run_install(deps=[])
check("only the main file is downloaded",
      len(LOG["downloads"]) == 1, LOG["downloads"])
check("the batch total is 1 file from the first callback onward",
      {t for _v, t in LOG["progress"]} == {1.0}, LOG["progress"])
check("percent never moves backwards", _monotonic(percents), percents)
check("percent finishes at exactly 100", percents[-1] == 100, percents)
check("the result reports the one installed file",
      result["installed"] == [MAIN_FILE], result)

# ---------------------------------------------------------------------------
print("\n2. main + 2 dependencies: 0 -> 100 across the batch, in file units")
# ---------------------------------------------------------------------------
DEPS = [_dep("fabric-api-id", API_FILE), _dep("cloth-config-id", CLOTH_FILE)]
result, percents = run_install(deps=DEPS)
check("all three files are downloaded (main first)",
      [f for _u, f in LOG["downloads"]] == [MAIN_FILE, API_FILE, CLOTH_FILE],
      LOG["downloads"])
check("the total (3) is reported on the FIRST callback - resolved before the "
      "first byte moved, so nothing rescales mid-flight",
      bool(LOG["progress"]) and LOG["progress"][0][1] == 3.0,
      LOG["progress"][:3])
check("the total never changes during the batch",
      {t for _v, t in LOG["progress"]} == {3.0}, LOG["progress"])
check("progress is reported in file units, exactly 1/3 per file",
      [round(v, 2) for v, _t in LOG["progress"]] ==
      [0.0, 0.33, 1.0, 1.0, 1.33, 2.0, 2.0, 2.33, 3.0],
      LOG["progress"])
check("percent never moves backwards - no restart for the deps",
      _monotonic(percents), percents)
check("percent finishes at exactly 100", percents[-1] == 100, percents)
check("the result reports every installed file",
      result["installed"] == [MAIN_FILE, API_FILE, CLOTH_FILE], result)

# ---------------------------------------------------------------------------
print("\n3. status text names the file's position in the batch")
# ---------------------------------------------------------------------------
result, _percents = run_install(deps=DEPS)
check("the dependency check is announced before the downloads",
      bool(LOG["status"]) and LOG["status"][0] == "Checking dependencies...",
      LOG["status"])
check("each dependency is labelled as file N of the batch",
      LOG["status"] == [
          "Checking dependencies...",
          f"Dependency 2/3: {mods.name_stem(API_FILE)}",
          f"Dependency 3/3: {mods.name_stem(CLOTH_FILE)}"],
      LOG["status"])

# ---------------------------------------------------------------------------
print("\n4. dependencies already installed are skipped, not re-downloaded")
# ---------------------------------------------------------------------------
result, percents = run_install(deps=DEPS, installed=("fabric-api-id",))
check("only the main mod and the missing dependency are downloaded",
      [f for _u, f in LOG["downloads"]] == [MAIN_FILE, CLOTH_FILE],
      LOG["downloads"])
check("the skipped dependency is reported and does not pad the total",
      result["skipped"] == 1 and {t for _v, t in LOG["progress"]} == {2.0},
      (result, LOG["progress"]))
check("percent still finishes at exactly 100", percents[-1] == 100, percents)

# ---------------------------------------------------------------------------
print("\n5. the main mod's own id can never come back as a dependency")
# ---------------------------------------------------------------------------
result, percents = run_install(deps=[_dep("sodium-id", MAIN_FILE)])
check("no self-copy is downloaded", len(LOG["downloads"]) == 1, LOG["downloads"])
check("it is counted as skipped, not as a pending file",
      result["skipped"] == 1 and {t for _v, t in LOG["progress"]} == {1.0},
      (result, LOG["progress"]))
check("percent still finishes at exactly 100", percents[-1] == 100, percents)

# ---------------------------------------------------------------------------
print("\n6. an unknown project (drag-drop) is still one clean climb")
# ---------------------------------------------------------------------------
result, percents = run_install(deps=DEPS, slug=None, project_id=None)
check("a project with no id/slug is never used as a dependency reference",
      LOG["dep_refs"] == [], LOG["dep_refs"])
check("the single file is the whole batch",
      {t for _v, t in LOG["progress"]} == {1.0}, LOG["progress"])
check("percent still finishes at exactly 100", percents[-1] == 100, percents)

# ---------------------------------------------------------------------------
print("\n7. a project resolved from the sidecar meta still batches upfront")
# ---------------------------------------------------------------------------
result, percents = run_install(deps=[_dep("fabric-api-id", API_FILE)],
                               slug=None, project_id=None,
                               meta_project="sodium-id", filename=MAIN_FILE)
check("dependencies are looked up for the id found in the meta",
      LOG["dep_refs"] == ["sodium-id"], LOG["dep_refs"])
check("the meta-resolved dependency is in the total before the main download",
      bool(LOG["progress"]) and LOG["progress"][0][1] == 2.0,
      LOG["progress"][:3])
check("both files are downloaded",
      [f for _u, f in LOG["downloads"]] == [MAIN_FILE, API_FILE],
      LOG["downloads"])
check("percent finishes at exactly 100", percents[-1] == 100, percents)

# ---------------------------------------------------------------------------
print("\n8. a failing dependency is reported, never raised")
# ---------------------------------------------------------------------------
result, percents = run_install(
    deps=DEPS,
    fail=(f"https://cdn.modrinth.com/data/fabric-api-id/versions/v/{API_FILE}",))
check("the main mod is still installed",
      MAIN_FILE in result["installed"], result)
check("the later dependency still installs",
      CLOTH_FILE in result["installed"], result)
check("the failure is named in the result",
      result["failed"] == [mods.name_stem(API_FILE)], result)
check("progress stays monotonic (no jump back for the failed file)",
      _monotonic(percents), percents)
check("the bar stops short of 100 rather than claiming the failed file - the "
      "UI's 'Installed, but failed' line carries the message",
      percents[-1] < 100, percents)

# ---------------------------------------------------------------------------
print("\n9. the UI label turns file units into a sentence the user can read")
# ---------------------------------------------------------------------------
# Pins the OTHER half of the fix: the core now reports file units, so the label
# has to say which file is in flight. Without "(file 2/3)" a multi-file install
# showed a percent that appeared to restart, which is what got reported.
from ui.mods_tab import batch_progress_text as _label  # noqa: E402

check("a single file shows a plain percent (no '(file 1/1)' noise)",
      _label(0.5, 1) == "Downloading… 50%", _label(0.5, 1))
check("the first byte of a multi-file batch is file 1, not file 0",
      _label(0, 3).endswith("(file 1/3)"), _label(0, 3))
check("a whole file finished means the NEXT one is in flight",
      _label(1.0, 3).endswith("(file 2/3)"), _label(1.0, 3))
check("the percent is of the WHOLE batch, never of the current file",
      _label(1.0, 3).startswith("Downloading… 33%"), _label(1.0, 3))
check("the last file reads as the last file, at 100%",
      _label(3, 3) == "Downloading… 100% (file 3/3)", _label(3, 3))
check("a zero total (unknown size) can't divide by zero",
      _label(0, 0) == "Downloading… 0%", _label(0, 0))
check("an out-of-range value can't claim a file that doesn't exist",
      _label(9, 3).endswith("(file 3/3)"), _label(9, 3))

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
