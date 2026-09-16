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

Report shape (a superset of mod_doctor's, so existing callers keep working):
  {"checked", "problems", "fixed", "unfixed", "sections", "summary"}
Every problem is {"section", "kind", "item", "detail", "fixed", "fix"?};
entries from the mods section keep their original "mod" key too.
"""
import json
import os
import re
import zipfile

from . import logging_setup  # noqa: F401  (installs the file log handlers)
from . import modpacks
from . import mods
from . import packformat
from . import server as server_module
from .paths import MINECRAFT_DIR, RESOURCEPACKS_DIR, SERVERS_DIR, SHADERPACKS_DIR

import logging

log = logging.getLogger(__name__)

ALL_SECTIONS = ("mods", "resourcepacks", "shaders", "modpacks", "plugins")

# Files a jar must carry (at the zip root) to be a loadable plugin. Paper reads
# plugin.yml / paper-plugin.yml, Spigot and Paper also accept bungee.yml for
# BungeeCord-style plugins, and Velocity uses velocity-plugin.json.
_PLUGIN_DESCRIPTORS = ("plugin.yml", "paper-plugin.yml", "bungee.yml",
                       "velocity-plugin.json")
_PLUGIN_NAME_RE = re.compile(r"^\s*name\s*:\s*[\"']?([^\"'\n#]+)", re.MULTILINE)


def run_doctor(mc_version: str | None = None, loader: str | None = None, *,
               # NOTE: auto_fix defaults to True ("fix what you find"). A
               # caller that only wants a REPORT must pass auto_fix=False
               # explicitly - the default quietly repairs.
               auto_fix: bool = True, check_online: bool = True,
               status_cb=None, include=None,
               version_id: str | None = None) -> dict:
    """Check (and, when auto_fix is on, repair) every kind of installed content.

    mc_version/loader describe the profile the user is working in. The
    resource-pack pass deliberately checks against ALL installed versions,
    because the shared resourcepacks/ folder is read by every one of them.

    include: optional iterable of section names to run only those (the UI uses
    it to scope a check to the tab the user is looking at).

    Never raises. Returns the report described in the module docstring."""
    wanted = tuple(include) if include else ALL_SECTIONS
    runners = {
        "mods": lambda: _mods_section(mc_version, loader, auto_fix,
                                      check_online, status_cb),
        "resourcepacks": lambda: _resourcepacks_section(mc_version, version_id,
                                                        auto_fix, status_cb),
        "shaders": lambda: _shaders_section(auto_fix, status_cb),
        "modpacks": lambda: _modpacks_section(mc_version, loader, auto_fix,
                                              check_online, status_cb),
        "plugins": lambda: _plugins_section(auto_fix, status_cb),
    }

    report = {"checked": 0, "problems": [], "fixed": [], "unfixed": [],
              "sections": {}, "summary": ""}
    for name in ALL_SECTIONS:
        if name not in wanted:
            continue
        try:
            checked, entries = runners[name]()
        except Exception:
            # One broken section must not take the others (or a launch) down;
            # the traceback still lands in the central file log.
            log.warning("doctor section %s failed", name, exc_info=True)
            continue
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
    if not report["problems"]:
        return f"Checked {report['checked']} item(s) - no problems found."
    fixed = len(report["fixed"])
    unfixed = len(report["unfixed"])
    text = f"Checked {report['checked']} item(s): fixed {fixed}"
    if unfixed:
        text += f", {unfixed} need attention"
    return text + "."


def _entry(section: str, kind: str, item: str, detail: str, fixed: bool,
           fix: str = "") -> dict:
    entry = {"section": section, "kind": kind, "item": item,
             "detail": detail, "fixed": bool(fixed)}
    if fix:
        entry["fix"] = fix
    return entry


def _say(status_cb, text: str) -> None:
    if not status_cb:
        return
    try:
        status_cb(text)
    except Exception:
        log.debug("doctor status callback failed", exc_info=True)


# ---------------------------------------------------------------------------
# Section: mods (delegates to cubeon/mods.py:mod_doctor)
# ---------------------------------------------------------------------------

def _mods_section(mc_version, loader, auto_fix, check_online, status_cb) -> tuple:
    if not mc_version or loader not in mods.MOD_CAPABLE_LOADERS:
        return 0, []
    _say(status_cb, "Checking your mods...")
    report = mods.mod_doctor(mc_version, loader, auto_fix=auto_fix,
                             check_online=check_online, status_cb=status_cb)
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
        entries.append(_entry(
            "shaders", "shader-structure", label, verdict["reason"], fixed, fix))
    return checked, entries


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
        except (OSError, json.JSONDecodeError):
            meta = None
        yield key, profile_dir, meta


def _profile_mod_count(profile_dir: str) -> int:
    try:
        return sum(1 for f in os.listdir(profile_dir)
                   if f.lower().endswith((".jar", ".jar.disabled")))
    except OSError:
        return 0


def _modpacks_section(mc_version, loader, auto_fix, check_online, status_cb) -> tuple:
    checked = 0
    entries = []
    for key, profile_dir, meta in _iter_modpack_markers():
        checked += 1
        pack_name = (meta or {}).get("name") or key

        if meta is None:
            # An unreadable marker means the Modpacks tab no longer lists this
            # pack while its profile folder and mods stay exactly as they are.
            # Removing the file is the fix - it is a tracking record, not
            # content.
            fixed = False
            fix = ""
            if auto_fix:
                try:
                    os.remove(os.path.join(profile_dir,
                                           modpacks.MODPACK_META_FILENAME))
                    fixed = True
                    fix = "removed the unreadable tracking file"
                except OSError:
                    log.warning("could not remove marker in %s", profile_dir,
                                exc_info=True)
            entries.append(_entry(
                "modpacks", "pack-marker", pack_name,
                "its tracking file (_modpack.json) is unreadable, so the pack "
                "isn't listed and Play can't pick it", fixed, fix))
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
        if pack_mc:
            installed = os.path.isdir(
                os.path.join(MINECRAFT_DIR, "versions", str(pack_mc)))
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
        if (pack_mc and pack_loader
                and (str(pack_mc), pack_loader) != (str(mc_version), loader)
                and pack_loader in mods.MOD_CAPABLE_LOADERS):
            try:
                nested = mods.mod_doctor(str(pack_mc), pack_loader,
                                         auto_fix=auto_fix, check_online=False)
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
                entries.append(_entry(
                    "plugins", "plugin-unreadable", label,
                    "the jar can't be read (a truncated download?), so the "
                    "server will fail to load it", False))
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
                entries.append(_entry(
                    "plugins", "plugin-not-a-plugin", label,
                    "it carries no plugin.yml/paper-plugin.yml, so it isn't a "
                    "plugin the server can load", fixed, fix))
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
                    fixed, fix))
    return checked, entries
