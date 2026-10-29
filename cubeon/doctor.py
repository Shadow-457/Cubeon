"""
One doctor for every kind of content the launcher installs.

`cubeon/mods.py:mod_doctor()` only ever knew about mods, so everything else the
launcher drops on disk was taken on trust: resource packs the game greets with
a red "Incompatible", shader zips whose `shaders/` folder is one level too
deep, modpack profiles whose mods went missing, and server plugin jars that
aren't plugins at all. This module runs the mod doctor AND those four checks
behind one call, so a single "Fix problems" action - and the automatic pass
before a launch - covers everything.

Sections (each independently fail-soft; a broken check costs a missed problem,
never a launch):

  mods          - cubeon/mods.py:mod_doctor, unchanged: duplicate copies,
                  missing required dependencies, jars built for another
                  loader/version, and Fabric `breaks` clashes.
  resourcepacks - the pack.mcmeta format range against EVERY installed version
                  (cubeon/packformat.py). This is the "Incompatible in game"
                  fix: packs live in one shared folder, so a pack built for one
                  version is judged by all of them.
  shaders       - structure only: shader packs carry no format, so the failure
                  modes are "shaders/ is nested inside a folder" (fixable by
                  flattening) or "this isn't a shader pack" (not fixable).
  modpacks      - every installed pack's marker vs its profile: unreadable
                  marker, mods that went missing, its Minecraft version not
                  installed, plus a filesystem-only mod pass on that pack's OWN
                  profile (the mods section only covers the active one).
  plugins       - each server's plugin jars: readable, actually a plugin (it
                  has a plugin descriptor), and no two enabled jars claiming
                  the same plugin name.
  launch        - the global launch config: a `custom_jvm_flags` token that is
                  not a JVM option is read by Java as the MAIN CLASS (crashed
                  26.3 with `ClassNotFoundException: 他他他` on 2026-10-25), and
                  an explicit `java_path` that no longer exists. Both are
                  auto-fixed by clearing the bad value so the launcher falls
                  back to its own defaults.

Report shape (a superset of mod_doctor's, so existing callers keep working):
  {"checked", "problems", "fixed", "unfixed", "sections", "summary"}
Every problem is {"section", "kind", "item", "detail", "fixed", "action", "fix"?};
`detail` is ALWAYS the concrete reason/error - including for entries that were
fixed - and `fix` says what was actually done. entries from the mods section
keep their original "mod" key too.

`format_problem()` / `report_lines()` render that pair the same way on every
surface ("Sodium: duplicate copies prevent loading -> disabled the older
copy"), so a fix can never hide the error that caused it.
"""
import json
import os
import re
import shutil
import time
import zipfile

from . import logging_setup  # noqa: F401  (installs the file log handlers)
from . import modpacks
from . import mods
from . import packformat
from . import server as server_module
from .paths import MINECRAFT_DIR, RESOURCEPACKS_DIR, SERVERS_DIR, SHADERPACKS_DIR

import logging

log = logging.getLogger(__name__)

ALL_SECTIONS = ("launch", "mods", "resourcepacks", "shaders", "modpacks",
                "plugins")

# Files a jar must carry (at the zip root) to be a loadable plugin. Paper reads
# plugin.yml / paper-plugin.yml, Spigot and Paper also accept bungee.yml for
# BungeeCord-style plugins, and Velocity uses velocity-plugin.json.
_PLUGIN_DESCRIPTORS = ("plugin.yml", "paper-plugin.yml", "bungee.yml",
                       "velocity-plugin.json")
_PLUGIN_NAME_RE = re.compile(r"^\s*name\s*:\s*[\"']?([^\"'\n#]+)", re.MULTILINE)


def run_doctor(mc_version: str | None = None, loader: str | None = None, *,
               auto_fix: bool = True, check_online: bool = True,
               status_cb=None, include=None, approve_cb=None, cancel_event=None,
               version_id: str | None = None,
               crash_text: str | None = None) -> dict:
    """Check (and, when auto_fix is on, repair) every kind of installed content.

    mc_version/loader describe the profile the user is working in. The
    resource-pack pass deliberately checks against ALL installed versions,
    because the shared resourcepacks/ folder is read by every one of them.

    include: optional iterable of section names to run only those (the UI uses
    it to scope a check to the tab the user is looking at).

    crash_text: the crashed game's log. Passed only by the crash report's
    Check & fix; the mods pass uses the lines that explicitly blame a mod to
    disable ONE installed culprit that local metadata cannot identify (a mixin
    clash, a loader resolution). Normal scans leave it empty.

    Existing mods can only be disabled or replaced after approve_cb(change)
    returns True. The report's changes list records these proposals and consent.

    Never raises. Returns the report described in the module docstring."""
    changes = []

    def review(change):
        changes.append(change)
        return approve_cb(change) is True if approve_cb else False

    wanted = tuple(include) if include else ALL_SECTIONS
    runners = {
        "launch": lambda: _launch_section(auto_fix, status_cb),
        "mods": lambda: _mods_section(mc_version, loader, auto_fix,
                                      check_online, status_cb, review, cancel_event,
                                      version_id=version_id,
                                      crash_text=crash_text),
        "resourcepacks": lambda: _resourcepacks_section(mc_version, version_id,
                                                        auto_fix, status_cb),
        "shaders": lambda: _shaders_section(auto_fix, status_cb),
        "modpacks": lambda: _modpacks_section(mc_version, loader, auto_fix,
                                              check_online, status_cb, review, cancel_event,
                                              version_id=version_id),
        "plugins": lambda: _plugins_section(auto_fix, status_cb),
    }

    report = {"checked": 0, "problems": [], "fixed": [], "unfixed": [],
              "sections": {}, "summary": "", "changes": changes, "cancelled": False}
    for name in ALL_SECTIONS:
        if cancel_event is not None and cancel_event.is_set():
            report["cancelled"] = True
            break
        if name not in wanted:
            continue
        try:
            checked, entries = runners[name]()
        except Exception as error:
            # One broken section must not take the others (or a launch) down;
            # the traceback still lands in the central file log. It is NOT
            # silent any more: a check that could not run must never leave the
            # summary saying "no problems found".
            log.warning("doctor section %s failed", name, exc_info=True)
            detail = (f"this check could not run: "
                      f"{type(error).__name__}: {error}".strip())
            entry = _entry(name, "section-failed", name, detail, False,
                           action="none")
            entries = [entry]
            checked = 0
            report["sections"][name] = {
                "checked": 0,
                "problems": 1,
                "fixed": 0,
                "error": str(error) or type(error).__name__,
            }
        else:
            report["sections"][name] = {
                "checked": checked,
                "problems": len(entries),
                "fixed": sum(1 for entry in entries if entry["fixed"]),
            }
        report["checked"] += checked
        report["problems"].extend(entries)
        for entry in entries:
            (report["fixed"] if entry["fixed"] else report["unfixed"]).append(entry)

    report["summary"] = _summarize(report)
    return report


def _summarize(report: dict) -> str:
    """One honest sentence: never "no problems found" after a failed or
    cancelled check (an incomplete scan is itself a result the user needs)."""
    checked = report.get("checked", 0)
    fixed = len(report.get("fixed") or [])
    unfixed = len(report.get("unfixed") or [])
    failed = [name for name, info in (report.get("sections") or {}).items()
              if isinstance(info, dict) and info.get("error")]
    if report.get("cancelled"):
        text = f"Check stopped early - {checked} item(s) checked"
        if fixed:
            text += f", {fixed} fixed"
        if failed:
            text += f", {len(failed)} check(s) could not run"
        return text + "."
    if failed:
        text = f"Checked {checked} item(s): fixed {fixed}"
        if unfixed:
            text += f", {unfixed} need attention"
        return (text + f", {len(failed)} check(s) could not run "
                f"({', '.join(sorted(failed))}).")
    if not report.get("problems"):
        if checked == 0:
            return "Nothing was checked - pick an instance with installed content."
        return f"Checked {checked} item(s) - no problems found."
    text = f"Checked {checked} item(s): fixed {fixed}"
    if unfixed:
        text += f", {unfixed} need attention"
    return text + "."


def _entry(section: str, kind: str, item: str, detail: str, fixed: bool,
           fix: str = "", action: str = "") -> dict:
    entry = {"section": section, "kind": kind, "item": item,
             "detail": detail, "fixed": bool(fixed),
             # Machine-readable outcome: disabled / enabled / installed /
             # replaced / repaired / removed / none. A fixed entry without a
             # more specific action is a repair.
             "action": action or ("repaired" if fixed else "none")}
    if fix:
        entry["fix"] = fix
    return entry


def format_problem(entry: dict) -> str:
    """Render one problem for a human: the ERROR first, then what was done.

    Every surface uses this so a successful fix can never replace the reason
    with "disabled it" and leave the user guessing what went wrong."""
    item = (entry.get("item") or entry.get("mod") or "Content")
    raw_detail = entry.get("detail") or entry.get("reason") or ""
    detail = str(raw_detail).strip()
    fix = str(entry.get("fix") or "").strip()
    if entry.get("fixed") and fix:
        return f"{item}: {detail} \u2192 {fix}" if detail else f"{item}: {fix}"
    if not detail:
        detail = "needs attention"
    return f"{item}: {detail}" if detail else str(item)


def report_lines(report: dict, limit: int = 12, *,
                 include_fixed: bool = True) -> list[str]:
    """Fixed first, then what still needs attention, capped with an honest tail.

    `detail` stays attached to fixed rows, so the inline result of an explicit
    repair explains both the error and the action."""
    entries = []
    if include_fixed:
        entries.extend(report.get("fixed") or [])
    entries.extend(report.get("unfixed") or [])
    lines = [format_problem(entry) for entry in entries[:max(0, int(limit))]]
    rest = len(entries) - len(lines)
    if rest > 0:
        lines.append(f"{rest} more result(s) not shown.")
    return lines


def _say(status_cb, text: str) -> None:
    if not status_cb:
        return
    try:
        status_cb(text)
    except Exception:
        log.debug("doctor status callback failed", exc_info=True)


# ---------------------------------------------------------------------------
# Section: launch config (global, not per-instance)
# ---------------------------------------------------------------------------

def _launch_section(auto_fix, status_cb) -> tuple:
    """Catch config values that make the next launch die before Minecraft.

    The 2026-10-25 crash was `custom_jvm_flags: "他他他"`: mll puts custom JVM
    args before the main class, so a bare token becomes the class name and
    Java reports `ClassNotFoundException: 他他他`. The doctor previously only
    looked at installed content, so "Fix crash" had nothing to fix even though
    the crash was entirely launcher config. Same for a Settings `java_path`
    that points at a deleted/moved binary.

    Allocated RAM is validated too: a hand-edited/half-migrated config can hold
    a string, a negative number, or more memory than the machine owns, and
    either shape makes Java refuse to start (-Xmx). Clamping it is a safe,
    reversible launcher-owned repair.
    """
    from .config import load_config, save_config, CONFIG_PATH
    from .launch import (invalid_custom_jvm_flags, _normalize_java_path,
                         _parse_custom_jvm_flags)

    if not os.path.isfile(CONFIG_PATH):
        return 0, []  # brand-new install: defaults are valid, nothing to report
    _say(status_cb, "Checking launch settings...")
    try:
        cfg = load_config()
    except Exception:
        return 0, []

    entries = []
    changed = False

    raw_flags = cfg.get("custom_jvm_flags") or ""
    bad_tokens = invalid_custom_jvm_flags(raw_flags)
    if bad_tokens:
        detail = (f"{', '.join(repr(t) for t in bad_tokens[:3])} "
                  f"{'is' if len(bad_tokens) == 1 else 'are'} not JVM flags. "
                  "Java reads a bare token as the main class, so the game "
                  "crashes with ClassNotFoundException before Minecraft starts.")
        fixed = False
        fix = ""
        if auto_fix:
            try:
                cfg["custom_jvm_flags"] = " ".join(
                    _parse_custom_jvm_flags(raw_flags))
                changed = True
                fixed = True
                fix = "removed the non-flag token(s) from custom JVM flags"
            except Exception:
                log.warning("clearing invalid custom JVM flags failed",
                            exc_info=True)
        entries.append(_entry("launch", "jvm-flags", "Custom JVM flags",
                              detail, fixed, fix,
                              action="repaired" if fixed else "none"))

    # --- allocated RAM -----------------------------------------------------
    ram_entry = _ram_problem(cfg)
    if ram_entry is not None:
        detail, target = ram_entry
        fixed = False
        fix = ""
        if auto_fix and target:
            cfg["ram_mb"] = target
            changed = True
            fixed = True
            fix = f"set allocated RAM to {target} MB"
        entries.append(_entry("launch", "ram", "Allocated RAM", detail,
                              fixed, fix,
                              action="repaired" if fixed else "none"))

    configured_java = cfg.get("java_path")
    if configured_java:
        candidate = _normalize_java_path(configured_java)
        if not (os.path.isfile(candidate) or shutil.which(candidate)):
            detail = (f"The Java path in Settings ({configured_java!r}) does "
                      "not exist, so launching falls back to auto-detect.")
            fixed = False
            fix = ""
            if auto_fix:
                cfg["java_path"] = None
                changed = True
                fixed = True
                fix = "reset Java path to auto-detect"
            entries.append(_entry("launch", "java-path", "Java path",
                                  detail, fixed, fix,
                                  action="repaired" if fixed else "none"))

    if changed:
        try:
            save_config(cfg)
        except Exception:
            log.warning("saving repaired launch config failed", exc_info=True)
            for entry in entries:
                if entry["fixed"]:
                    entry["fixed"] = False
                    entry["action"] = "none"
                    entry.pop("fix", None)
    return 1, entries


def _ram_problem(cfg: dict):
    """(detail, safe_target_mb) when `ram_mb` cannot be used, else None.

    The configured value is quoted in the detail so the user can see exactly
    what was wrong. The replacement is the launcher's own recommendation,
    never more than the machine can actually back."""
    from .config import get_system_ram_mb, recommended_max_ram_mb

    raw = cfg.get("ram_mb")
    try:
        system = int(get_system_ram_mb())
    except Exception:
        system = 0
    recommended = max(1024, int(recommended_max_ram_mb(system) if system else 4096))
    target = max(1024, min(recommended, 6144))
    if system:
        target = min(target, max(1024, system - 1024))

    if isinstance(raw, bool) or raw is None:
        return (f"Allocated RAM ({raw!r}) isn't a number, so Java can't build "
                "a usable -Xmx value.", target)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return (f"Allocated RAM ({raw!r}) isn't a whole number of MB, so Java "
                "can't build a usable -Xmx value.", target)
    if value < 1024:
        return (f"Allocated RAM ({value} MB) is below the 1 GB minimum "
                "Minecraft needs; the game will run out of memory or fail to "
                "start.", target)
    if system and value > system:
        return (f"Allocated RAM ({value} MB) is larger than this machine's "
                f"{system} MB, so the JVM may refuse to start or swap hard.",
                target)
    return None


# ---------------------------------------------------------------------------
# Section: mods (delegates to cubeon/mods.py:mod_doctor)
# ---------------------------------------------------------------------------

def _mods_section(mc_version, loader, auto_fix, check_online, status_cb,
                  approve_cb, cancel_event, version_id=None,
                  crash_text=None) -> tuple:
    if not mc_version or loader not in mods.MOD_CAPABLE_LOADERS:
        return 0, []
    _say(status_cb, "Checking your mods...")
    report = mods.mod_doctor(mc_version, loader, auto_fix=auto_fix,
                             check_online=check_online, status_cb=status_cb,
                             approve_cb=approve_cb, cancel_event=cancel_event,
                             version_id=version_id, crash_text=crash_text)
    entries = []
    for problem in report.get("problems") or []:
        # mod_doctor's entries keep their own keys ("mod", "kind", "detail",
        # "fixed", "fix"); add the section + a generic "item" so the merged
        # report is uniform without breaking the existing contract (the tests
        # and the UI read "kind"/"fixed", and "mod" stays valid).
        entry = dict(problem)
        entry["section"] = "mods"
        entry["item"] = entry.get("mod") or entry.get("item") or "?"
        entry["fixed"] = bool(entry.get("fixed"))
        entries.append(entry)
    return report.get("checked", 0), entries


# ---------------------------------------------------------------------------
# Section: resource packs (pack.mcmeta format vs every installed version)
# ---------------------------------------------------------------------------

def _iter_content_packs(directory: str):
    """(name, path) for every pack in a content folder: .zip files AND
    folder packs (an unpacked pack directory is just as loadable to the
    game - skipping those used to leave them invisible to the doctor)."""
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return
    for name in names:
        if name.startswith("."):
            continue
        full = os.path.join(directory, name)
        if os.path.isdir(full):
            yield name, full
        elif os.path.isfile(full) and name.lower().endswith(".zip"):
            yield name, full


def _resourcepacks_section(mc_version, version_id, auto_fix, status_cb) -> tuple:
    targets = packformat.installed_resource_formats(mc_version, version_id)
    checked = 0
    entries = []
    for name, path in _iter_content_packs(RESOURCEPACKS_DIR):
        checked += 1
        verdict = packformat.pack_verdict(path, targets)
        if verdict["ok"] is not False:
            # True = accepted everywhere. None = the target format can't be
            # determined (snapshot / version not installed yet) - never guessed
            # at, and never "fixed".
            continue
        label = os.path.splitext(name)[0]
        fixed = False
        fix = ""
        if auto_fix:
            _say(status_cb, f"Fixing {label}")
            try:
                repair = packformat.repair_pack(path, targets)
                fixed = bool(repair.get("changed"))
                if fixed:
                    after = repair.get("after") or {}
                    rng = after.get("supported_formats")
                    fix = f"resource format range widened to {rng[0]}-{rng[1]}"
                    if repair.get("flattened"):
                        fix += ", folder layout flattened"
            except Exception:
                log.warning("repairing resource pack %s failed", name,
                            exc_info=True)
        entries.append(_entry(
            "resourcepacks", "pack-format", label, verdict["reason"], fixed, fix))
    return checked, entries


# ---------------------------------------------------------------------------
# Section: shaders (structure - shader packs have no pack_format)
# ---------------------------------------------------------------------------

def _shaders_section(auto_fix, status_cb) -> tuple:
    checked = 0
    entries = []
    for name, path in _iter_content_packs(SHADERPACKS_DIR):
        checked += 1
        verdict = packformat.shader_verdict(path)
        if verdict["ok"]:
            continue
        label = os.path.splitext(name)[0]
        fixed = False
        fix = ""
        wrapper = verdict.get("wrapper")
        if auto_fix and wrapper:
            # "shaders/" one folder down is the one structurally fixable case:
            # flattening puts it where Iris/OptiFine look for it.
            _say(status_cb, f"Fixing {label}")
            try:
                if packformat.flatten_pack(path, wrapper):
                    fixed = True
                    fix = f"moved shaders/ up out of '{wrapper}/'"
            except Exception:
                log.warning("flattening shader pack %s failed", name,
                            exc_info=True)
        elif auto_fix:
            # A pack with a pack.mcmeta and no shaders/ is a RESOURCE pack in
            # the wrong folder - the game will never load it there. Moving it
            # to resourcepacks/ makes it usable instead of leaving a dead file.
            moved = _move_to_resourcepacks(name, path, status_cb)
            if moved:
                fixed = True
                fix = ("moved it to resourcepacks/ - it is a resource pack, "
                       "not a shader pack")
        entries.append(_entry(
            "shaders", "shader-structure", label, verdict["reason"], fixed, fix,
            action="repaired" if fixed else "none"))
    return checked, entries


def _move_to_resourcepacks(name: str, path: str, status_cb) -> bool:
    """Move a misplaced resource pack out of shaderpacks/. Never overwrites."""
    try:
        if packformat.read_pack_meta(path)[0] is None:
            return False
        os.makedirs(RESOURCEPACKS_DIR, exist_ok=True)
        destination = os.path.join(RESOURCEPACKS_DIR, name)
        if os.path.lexists(destination):
            return False
        _say(status_cb, f"Moving {name} to resource packs")
        shutil.move(path, destination)
        log.info("moved misplaced resource pack %s from shaderpacks/", name)
        return True
    except Exception:
        log.warning("moving misplaced resource pack %s failed", name,
                    exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Section: modpacks (the marker vs the profile it points at)
# ---------------------------------------------------------------------------

def _iter_modpack_markers():
    """(profile_key, profile_dir, meta) for every installed modpack.

    Reads the markers directly instead of using list_installed_modpacks(),
    because the doctor needs the profile DIRECTORY too - and a marker that
    fails to parse has to be visible, since that is one of the problems it
    fixes."""
    profiles_dir = modpacks.PROFILES_DIR
    try:
        keys = sorted(os.listdir(profiles_dir))
    except OSError:
        return
    for key in keys:
        profile_dir = os.path.join(profiles_dir, key)
        marker = os.path.join(profile_dir, modpacks.MODPACK_META_FILENAME)
        if not os.path.isfile(marker):
            continue
        try:
            with open(marker, "r", encoding="utf-8") as fh:
                meta = json.load(fh)
        except (OSError, ValueError):
            # invalid UTF-8 is a ValueError, not a JSONDecodeError.
            meta = None
        yield key, profile_dir, meta


def _profile_mod_count(profile_dir: str) -> int:
    try:
        return sum(1 for f in os.listdir(profile_dir)
                   if f.lower().endswith((".jar", ".jar.disabled")))
    except OSError:
        return 0


def _modpacks_section(mc_version, loader, auto_fix, check_online, status_cb, approve_cb, cancel_event,
                      version_id=None) -> tuple:
    checked = 0
    entries = []
    for key, profile_dir, meta in _iter_modpack_markers():
        checked += 1
        pack_name = (meta or {}).get("name") or key

        if meta is None:
            # An unreadable marker means the Modpacks tab no longer lists this
            # pack while its profile folder and mods stay exactly as they are.
            # Move the broken file aside (never delete it - it may be the only
            # record of where the pack came from) and say what that means: the
            # pack disappears from the tab until it is reinstalled.
            fixed = False
            fix = ""
            if auto_fix:
                marker = os.path.join(profile_dir,
                                      modpacks.MODPACK_META_FILENAME)
                backup = f"{marker}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}"
                try:
                    os.replace(marker, backup)
                    fixed = True
                    fix = (f"moved the unreadable tracking file aside as "
                           f"{os.path.basename(backup)}; the pack is no longer "
                           "listed until it is reinstalled (its mods are kept)")
                except OSError:
                    log.warning("could not remove marker in %s", profile_dir,
                                exc_info=True)
            entries.append(_entry(
                "modpacks", "pack-marker", pack_name,
                "its tracking file (_modpack.json) is unreadable, so the pack "
                "isn't listed and Play can't pick it", fixed, fix,
                action="removed" if fixed else "none"))
            # Without the marker there is no reliable mc_version/loader, so
            # the version/profile checks below cannot run for this pack.
            continue

        expected = meta.get("mod_count")
        if isinstance(expected, int) and expected > 0 \
                and _profile_mod_count(profile_dir) == 0:
            # The pack's mods are gone (a wiped folder, or a profile reused and
            # emptied): Play would launch a broken instance. Nothing can be
            # re-derived offline - only a reinstall restores that exact build -
            # so this is reported, never silently "fixed".
            entries.append(_entry(
                "modpacks", "pack-mods-missing", pack_name,
                f"the pack installed {expected} mod(s) but the profile now has "
                "none - reinstall the pack to rebuild it", False))

        pack_mc = meta.get("mc_version")
        pack_version_id = meta.get("version_id")
        if pack_mc:
            versions_dir = os.path.join(MINECRAFT_DIR, "versions")
            installed = os.path.isdir(os.path.join(versions_dir, str(pack_mc)))
            if pack_version_id:
                installed = installed and os.path.isdir(
                    os.path.join(versions_dir, str(pack_version_id)))
            if not installed:
                entries.append(_entry(
                    "modpacks", "pack-version-missing", pack_name,
                    f"its Minecraft {pack_mc} client isn't installed, so Play "
                    "can't launch it", False))

        # The mods section only checks the profile the user is in; a pack's own
        # profile needs the same duplicate/conflict hygiene. Filesystem-only
        # (check_online=False) because a per-pack API pass would hammer the API
        # once per installed pack.
        pack_loader = meta.get("loader")
        # Same instance as the one the outer mods section just checked? Then
        # skip - otherwise every problem would be reported twice. Compare the
        # instance id when both sides have one, so two packs that share an
        # (mc_version, loader) pair are still checked separately.
        if pack_version_id or version_id:
            same_instance = str(pack_version_id or "") == str(version_id or "")
        else:
            same_instance = (str(pack_mc), pack_loader) == (str(mc_version), loader)
        if (pack_mc and pack_loader and not same_instance
                and pack_loader in mods.MOD_CAPABLE_LOADERS):
            try:
                nested = mods.mod_doctor(str(pack_mc), pack_loader,
                                         auto_fix=auto_fix, check_online=False, approve_cb=approve_cb,
                                         cancel_event=cancel_event,
                                         version_id=pack_version_id)
            except Exception:
                log.warning("mod check for modpack %s failed", pack_name,
                            exc_info=True)
                nested = {}
            for problem in nested.get("problems") or []:
                entry = dict(problem)
                entry["section"] = "modpacks"
                entry["item"] = f"{pack_name}: {entry.get('mod') or '?'}"
                entry["fixed"] = bool(entry.get("fixed"))
                entries.append(entry)
    return checked, entries


# ---------------------------------------------------------------------------
# Section: server plugins (is it a plugin, and is it the only copy?)
# ---------------------------------------------------------------------------

def _plugin_identity(jar_path: str) -> tuple:
    """(plugin_name_or_None, descriptor_or_None, readable).

    A None name with a None descriptor means the jar carries no plugin
    descriptor at all - dead weight the server silently ignores, which is
    exactly what "I installed a plugin and nothing happened" looks like."""
    try:
        with zipfile.ZipFile(jar_path) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
    except (OSError, zipfile.BadZipFile):
        return None, None, False

    by_base = {n.split("/")[-1].lower(): n for n in names}
    descriptor = next((by_base[d] for d in _PLUGIN_DESCRIPTORS if d in by_base),
                      None)
    stem = os.path.splitext(os.path.basename(jar_path))[0]
    if descriptor is None:
        return None, None, True

    raw = ""
    try:
        with zipfile.ZipFile(jar_path) as zf:
            raw = zf.read(descriptor).decode("utf-8", "replace")
    except (OSError, KeyError, zipfile.BadZipFile):
        return stem, descriptor, True

    if descriptor.endswith(".json"):
        try:
            data = json.loads(raw)
        except ValueError:
            return stem, descriptor, True
        if isinstance(data, dict):
            name = data.get("name") or data.get("id")
            if name:
                return str(name).strip(), descriptor, True
    else:
        # plugin.yml / bungee.yml / paper-plugin.yml are YAML, but every one of
        # them opens with a plain top-level `name:` - no parser needed.
        match = _PLUGIN_NAME_RE.search(raw)
        if match:
            return match.group(1).strip(), descriptor, True
    return stem, descriptor, True


def _iter_server_ids():
    try:
        names = sorted(os.listdir(SERVERS_DIR))
    except OSError:
        return
    for name in names:
        if os.path.isdir(os.path.join(SERVERS_DIR, name)):
            yield name


def _looks_like_client_mod(jar_path: str) -> bool:
    """True when the jar declares a Minecraft mod, not a server plugin.

    This turns "it carries no plugin descriptor" into the actionable truth:
    the user put a mod in the server's plugins/ folder."""
    try:
        with zipfile.ZipFile(jar_path) as zf:
            names = {n.replace("\\", "/").lower() for n in zf.namelist()}
    except (OSError, zipfile.BadZipFile):
        return False
    return any(name in names for name in (
        "fabric.mod.json", "quilt.mod.json", "meta-inf/mods.toml",
        "meta-inf/neoforge.mods.toml", "mcmod.info"))


def _plugins_section(auto_fix, status_cb) -> tuple:
    checked = 0
    entries = []
    for server_id in _iter_server_ids():
        plugins_dir = os.path.join(SERVERS_DIR, server_id, "plugins")
        if not os.path.isdir(plugins_dir):
            continue
        # Never touch a running server's plugins: the jars are in use (locked
        # on Windows) and a half-applied change would only muddy the next
        # start.
        try:
            if server_module.is_server_running(server_id):
                continue
        except Exception:
            log.debug("could not check whether server %s is running",
                      server_id, exc_info=True)

        enabled = [p for p in server_module.list_plugins(server_id)
                   if p.get("enabled") and not p.get("protected")]
        by_name: dict = {}
        for plugin in enabled:
            checked += 1
            jar_path = os.path.join(plugins_dir, plugin["filename"])
            label = plugin.get("display_name") or plugin["filename"]
            name, descriptor, readable = _plugin_identity(jar_path)

            if not readable:
                fixed = False
                fix = ""
                if auto_fix:
                    try:
                        os.rename(jar_path, jar_path + ".disabled")
                        fixed = True
                        fix = "disabled it (kept on disk, the server skips it)"
                    except OSError:
                        log.warning("could not disable unreadable plugin %s",
                                    jar_path, exc_info=True)
                entries.append(_entry(
                    "plugins", "plugin-unreadable", label,
                    "the jar can't be read (a truncated download?), so the "
                    "server will fail to load it", fixed, fix,
                    action="disabled" if fixed else "none"))
                continue
            if descriptor is None:
                fixed = False
                fix = ""
                if auto_fix:
                    try:
                        os.rename(jar_path, jar_path + ".disabled")
                        fixed = True
                        # The file is kept: this is the same reversible
                        # disable the plugin list already understands.
                        fix = "disabled it (kept on disk, the server skips it)"
                    except OSError:
                        log.warning("could not disable %s", jar_path,
                                    exc_info=True)
                detail = ("it carries no plugin.yml/paper-plugin.yml, so it "
                          "isn't a plugin the server can load")
                if _looks_like_client_mod(jar_path):
                    detail = ("this is a Minecraft client mod, not a server "
                              "plugin - it has no plugin.yml/paper-plugin.yml "
                              "and the server ignores it")
                entries.append(_entry(
                    "plugins", "plugin-not-a-plugin", label,
                    detail, fixed, fix,
                    action="disabled" if fixed else "none"))
                continue
            by_name.setdefault((name or label).lower(), []).append(
                (jar_path, name or label))

        # Duplicates: two enabled jars claiming one plugin name. Paper silently
        # ignores the second and only logs it, which reads as "my plugin update
        # did nothing". Keep the newest file, disable the rest - reversible,
        # and the same convention duplicate mods use.
        for group in by_name.values():
            if len(group) < 2:
                continue

            def _mtime(item):
                try:
                    return os.path.getmtime(item[0])
                except OSError:
                    return 0.0

            for jar_path, display in sorted(group, key=_mtime,
                                            reverse=True)[1:]:
                fixed = False
                fix = ""
                if auto_fix:
                    try:
                        os.rename(jar_path, jar_path + ".disabled")
                        fixed = True
                        fix = "disabled this older copy"
                    except OSError:
                        log.warning("could not disable duplicate plugin %s",
                                    jar_path, exc_info=True)
                entries.append(_entry(
                    "plugins", "plugin-duplicate", display,
                    "another enabled jar already provides the plugin "
                    f"'{display}' - the server silently ignores this one",
                    fixed, fix,
                    action="disabled" if fixed else "none"))
    return checked, entries
