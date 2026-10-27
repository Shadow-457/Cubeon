"""Crash-log diagnosis and repair for Minecraft launches.

This is the engine behind the Play card's **Fix crash** button. It reads the
newest Minecraft crash evidence (``crash-reports/crash-*.txt`` first, then
``logs/latest.log``, then Cubeon's own game-session log), recognises the
handful of failure shapes that actually account for most crashes, and applies
only the repairs it can verify afterwards.

Design rules:

* **Evidence first.** A fix is only proposed when a specific line in the log
  proves the cause. No signature match means "couldn't identify it", never a
  guessed repair. This is what keeps the fix rate honest instead of claiming
  a 90% success rate it cannot back up.
* **Reversible.** Mod repairs use the doctor's existing disable-not-delete
  path. Config repairs only clear values Cubeon itself owns.
* **Never raises.** A crash path must not be able to break the launcher.
* **Verifiable.** ``repair()`` re-checks what it changed (file disabled, RAM
  value stored, flags cleared) and reports a fix only when that check passes.

The module is intentionally dependency-light: it imports ``mods`` and
``launch`` lazily so importing the crash path cannot pull the whole network
stack into a launcher start.
"""
from __future__ import annotations

import json
import logging
import os
import re

from .paths import CUBEON_HOME, MINECRAFT_DIR

log = logging.getLogger(__name__)

# Only the tail of a huge log is useful: a mod that spams a stack trace every
# tick can write megabytes, and the crash cause is in the last screenful.
MAX_LOG_BYTES = 512 * 1024
EVIDENCE_CHARS = 1200

# Signatures, most-specific first. ``confidence`` is the prior that the
# signature identifies the real cause when its patterns match. Only >= 0.8 is
# auto-repaired; everything else is reported with the evidence.
_RULES = (
    {
        "signature": "out-of-memory",
        "cause": "Minecraft ran out of memory.",
        "confidence": 0.94,
        "patterns": (
            r"java\.lang\.outofmemoryerror",
            r"\boutofmemoryerror\b",
            r"\bjava heap space\b",
            r"\bgc overhead limit exceeded\b",
            r"could not reserve enough space for .* object heap",
            r"insufficient memory for the java runtime",
        ),
    },
    {
        "signature": "wrong-java",
        "cause": "Minecraft was started with the wrong Java version.",
        "confidence": 0.97,
        "patterns": (
            r"unsupportedclassversionerror",
            r"unsupported class file major version",
            r"class file version \d+(?:\.\d+)+",
            r"has been compiled by a more recent version of the java runtime",
            r"requires java (?:se )?\d+",
        ),
    },
    {
        "signature": "java-missing",
        "cause": "Java could not be started at all.",
        "confidence": 0.93,
        "patterns": (
            r"cannot run program\s+\"?javaw?\"?",
            r"could not create the java virtual machine",
            r"error: could not find or load main class",
        ),
    },
    {
        "signature": "bad-jvm-option",
        "cause": "Java rejected a launch option.",
        "confidence": 0.95,
        "patterns": (
            r"unrecognized option\s*:",
            r"unrecognized vm option",
            r"error: could not find or load main class (?!net\.minecraft)",
        ),
    },
    {
        "signature": "duplicate-mods",
        "cause": "Two copies of the same mod are installed.",
        "confidence": 0.96,
        "patterns": (
            r"duplicatemodsfoundexception",
            r"\bduplicate mods?\b",
            r"found duplicate mod",
            r"two mods with the same id",
            r"duplicate mod id",
        ),
    },
    {
        "signature": "missing-dependency",
        "cause": "A mod is missing a dependency it requires.",
        "confidence": 0.92,
        "patterns": (
            r"missing or unsupported mandatory dependencies",
            r"modresolutionexception",
            r"requires .* which is missing",
            r"depends on .* which is missing",
            r"requires .* version .* or later",
            r"no mod named .* was found",
            r"which is missing!",
        ),
    },
    {
        "signature": "incompatible-mods",
        "cause": "The installed mods do not match this Minecraft version or loader.",
        "confidence": 0.9,
        "patterns": (
            r"incompatible mod set",
            r"mod resolution encountered an incompatible",
            r"is not compatible with",
            r"requires minecraft .* but",
            r"requires .* (?:fabric|quilt|forge|neoforge).* but",
            r"incompatibleclasschangeerror",
        ),
    },
    {
        "signature": "mod-conflict",
        "cause": "Two mods are conflicting with each other.",
        "confidence": 0.86,
        "patterns": (
            r"mixin apply failed",
            r"mixin.*(?:failed|exception)",
            r"injectionerror",
            r"nosuchmethoderror",
            r"abstractmethoderror",
            r"illegalaccesserror",
        ),
    },
    {
        "signature": "corrupt-jar",
        "cause": "A mod jar is corrupt or incomplete.",
        "confidence": 0.93,
        "patterns": (
            r"invalid or corrupted jarfile",
            r"invalid loc header",
            r"error in opening zip file",
            r"unable to access jarfile",
            r"zipException",
            r"bad zip file",
        ),
    },
    {
        "signature": "incomplete-install",
        "cause": "This instance's Minecraft files are incomplete.",
        "confidence": 0.9,
        "patterns": (
            r"knotclient",
            r"knotserver",
            r"could not find or load main class net\.minecraft",
            r"failed to locate library",
        ),
    },
    {
        "signature": "graphics-driver",
        "cause": "The graphics driver could not start the game window.",
        "confidence": 0.88,
        "patterns": (
            r"glfw error",
            r"failed to create window",
            r"pixel format not accelerated",
            r"no opengl context",
            r"exception_access_violation",
            r"ig7icd",
            r"nvoglv",
            r"amdgv",
            r"libgallium",
        ),
    },
    {
        "signature": "corrupt-world",
        "cause": "A world or datapack could not be loaded.",
        "confidence": 0.82,
        "patterns": (
            r"failed to load datapacks",
            r"error loading registry",
            r"world .* corrupt",
        ),
    },
)

# Signatures whose repair is a mod-profile pass (dependency/conflict/duplicate
# handling in cubeon/mods.py). These are exactly the checks the user asked the
# doctor to own during a mod install.
MOD_SIGNATURES = {
    "duplicate-mods",
    "missing-dependency",
    "incompatible-mods",
    "mod-conflict",
}

_MOD_TOKEN_RE = re.compile(
    r"(?i)\b(?:mod|modid)\s*[\"'`]?([a-z0-9_.-]{2,64})")
_JAR_RE = re.compile(r"([A-Za-z0-9_.+\-]+)\.jar\b")
_NOT_A_MOD = {
    "minecraft", "java", "javaw", "fabric", "fabricloader", "quilt",
    "quilt_loader", "forge", "neoforge", "lwjgl", "log4j", "gson", "asm",
    "mixinextras", "mixin", "authlib", "brigadier", "datafixerupper",
    "client", "server", "main", "mods", "core", "api",
}


def _read_tail(path: str, limit: int = MAX_LOG_BYTES) -> str:
    try:
        size = os.path.getsize(path)
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            if size > limit:
                handle.seek(size - limit)
                handle.readline()
            return handle.read()
    except OSError:
        return ""


def _recent_files(directory: str, *, suffixes=(".txt", ".log")) -> list[str]:
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    found = []
    for name in names:
        if not name.lower().endswith(suffixes):
            continue
        full = os.path.join(directory, name)
        try:
            found.append((os.path.getmtime(full), full))
        except OSError:
            continue
    return [path for _mtime, path in sorted(found, reverse=True)]


def crash_log_candidates() -> list[str]:
    """Crash evidence paths, newest and most specific first. Never raises.

    A Minecraft crash report is the strongest evidence, so reports come first.
    ``latest.log`` follows because some failures (a JVM refusing to start, a
    mod loader abort) never reach the crash-report writer. Cubeon's own game
    logs are the last resort for a launch that died before Minecraft opened its
    log file.
    """
    out = []
    out.extend(_recent_files(os.path.join(MINECRAFT_DIR, "crash-reports")))
    latest = os.path.join(MINECRAFT_DIR, "logs", "latest.log")
    if os.path.isfile(latest):
        out.append(latest)
    out.extend(_recent_files(CUBEON_HOME, suffixes=(".log",)))
    # De-duplicate while keeping order.
    seen = set()
    unique = []
    for path in out:
        real = os.path.abspath(path)
        if real not in seen:
            seen.add(real)
            unique.append(path)
    return unique


def latest_crash_log(*, after: float | None = None) -> tuple[str | None, str]:
    """The newest crash evidence and its text, or ``(None, "")``.

    ``after`` limits the search to files written at/after that timestamp, so a
    Fix-crash click after a launch does not resurrect an old crash report from
    a different failure.
    """
    for path in crash_log_candidates():
        try:
            if after is not None and os.path.getmtime(path) < after:
                continue
        except OSError:
            continue
        text = _read_tail(path)
        if text.strip():
            return path, text
    return None, ""


def _evidence(text: str) -> str:
    """The most relevant lines around the first recognised failure."""
    lines = text.splitlines()
    markers = (
        "exception", "error", "caused by", "failed", "missing", "requires",
        "incompatible", "duplicate", "outofmemory", "unrecognized",
        "unsupported", "corrupt", "glfw", "mixin",
    )
    picked = []
    for index, line in enumerate(lines):
        low = line.lower()
        if any(marker in low for marker in markers):
            start = max(0, index - 1)
            end = min(len(lines), index + 3)
            picked.extend(lines[start:end])
            if len(picked) >= 14:
                break
    joined = "\n".join(picked) or "\n".join(lines[-12:])
    return joined[:EVIDENCE_CHARS]


def _mod_names(text: str) -> list[str]:
    names = set()
    for match in _MOD_TOKEN_RE.finditer(text or ""):
        name = match.group(1).strip("._-").lower()
        if name and name not in _NOT_A_MOD:
            names.add(name)
    for match in _JAR_RE.finditer(text or ""):
        stem = match.group(1)
        # Strip a version suffix: sodium-fabric-0.6.0+mc1.21.1 -> sodium-fabric
        for part in re.split(r"[-_+]", stem):
            part = part.strip("._-").lower()
            if part and part not in _NOT_A_MOD and not re.fullmatch(r"\d+(?:\.\d+)*", part):
                names.add(part)
                break
    return sorted(names)[:20]


def classify(text: str) -> dict:
    """Identify a crash from its log text. Never raises.

    Returns ``{"signature", "cause", "confidence", "evidence", "mods",
    "recognised"}``. ``recognised`` is False when no rule matched, which the
    UI must treat as "couldn't identify it" rather than a failed fix.
    """
    low = (text or "").lower()
    for rule in _RULES:
        if any(re.search(pattern, low) for pattern in rule["patterns"]):
            return {
                "signature": rule["signature"],
                "cause": rule["cause"],
                "confidence": rule["confidence"],
                "evidence": _evidence(text),
                "mods": _mod_names(text),
                "recognised": True,
            }
    return {
        "signature": "unknown",
        "cause": "Cubeon couldn't identify this crash from the log.",
        "confidence": 0.0,
        "evidence": _evidence(text),
        "mods": _mod_names(text),
        "recognised": False,
    }


def _memory_target(current: int) -> int:
    try:
        from .config import get_system_ram_mb, recommended_max_ram_mb
        system = int(get_system_ram_mb())
        recommended = int(recommended_max_ram_mb(system))
    except Exception:
        system, recommended = 8192, 4096
    try:
        current = int(current)
    except (TypeError, ValueError):
        current = 4096
    # One step up, never beyond what the machine can spare, and never above
    # 8 GB for a client heap. The old advice ("lower RAM") is exactly wrong
    # for an OutOfMemoryError at 4 GB on a 16 GB machine.
    spare = max(system - 2048, 4096)
    target = min(max(current + 2048, 4096), max(recommended, 6144), spare, 8192)
    return int(target // 512 * 512)


def _fix_memory(mc_version=None) -> dict:
    try:
        from .config import load_config, save_config
        cfg = load_config() or {}
        current = cfg.get("ram_mb", 4096)
        target = _memory_target(current)
        if target <= int(current or 0):
            return {"fixed": False, "detail": (
                f"already allocating {current} MB, and this machine has no "
                "spare RAM to raise it safely")}
        cfg["ram_mb"] = target
        save_config(cfg)
        stored = (load_config() or {}).get("ram_mb")
        return {
            "fixed": int(stored or 0) == target,
            "detail": f"raised the game's RAM from {current} MB to {target} MB",
            "ram_mb": target,
        }
    except Exception:
        log.warning("crash doctor could not raise RAM", exc_info=True)
        return {"fixed": False, "detail": "could not update the RAM setting"}


def _fix_java(mc_version=None, version_id=None) -> dict:
    try:
        from .config import load_config, save_config
        from . import launch
        cfg = load_config() or {}
        configured = cfg.get("java_path")
        target_version = version_id or mc_version
        required = None
        try:
            required = launch.required_java_major(target_version or "")
        except Exception:
            required = None
        current_major = None
        if configured:
            try:
                current_major = launch.java_major_version(configured)
            except Exception:
                current_major = None
        if required and current_major and current_major >= required:
            return {"fixed": False, "detail": (
                f"Java {current_major} already meets this version's Java "
                f"{required} requirement")}
        replacement = None
        try:
            replacement = launch.find_java_for_version(target_version or "")
        except Exception:
            replacement = None
        changed = False
        if replacement and replacement != configured:
            cfg["java_path"] = replacement
            changed = True
        elif configured:
            cfg["java_path"] = None
            changed = True
        if changed:
            save_config(cfg)
        return {
            "fixed": changed,
            "detail": (f"switched Java to {replacement}" if replacement
                       else "reset Java to auto-detect"),
        }
    except Exception:
        log.warning("crash doctor could not repair Java", exc_info=True)
        return {"fixed": False, "detail": "could not change the Java setting"}


def _fix_jvm_flags(text: str = "") -> dict:
    try:
        from .config import load_config, save_config
        from . import launch
        cfg = load_config() or {}
        raw = cfg.get("custom_jvm_flags") or ""
        bad = list(launch.invalid_custom_jvm_flags(raw) or [])
        for match in re.finditer(r"(?i)unrecognized (?:vm )?option\s*:\s*(\S+)", text or ""):
            token = match.group(1).strip().strip("'\"")
            if token and token not in bad:
                bad.append(token)
        if not bad:
            return {"fixed": False, "detail": "no invalid JVM flags were found"}
        keep = [token for token in launch._parse_custom_jvm_flags(raw)
                if token not in bad]
        cfg["custom_jvm_flags"] = " ".join(keep)
        save_config(cfg)
        stored = (load_config() or {}).get("custom_jvm_flags") or ""
        return {
            "fixed": not launch.invalid_custom_jvm_flags(stored),
            "detail": "removed the JVM option(s) Java rejected",
        }
    except Exception:
        log.warning("crash doctor could not repair JVM flags", exc_info=True)
        return {"fixed": False, "detail": "could not change the JVM flags"}


def _match_installed_mods(mc_version, loader, version_id, names) -> list[dict]:
    """Installed mods whose id, slug, or filename stem matches a log token."""
    try:
        from . import mods
        installed = mods.list_mods(mc_version, loader, version_id)
    except Exception:
        return []
    wanted = {str(name).lower() for name in names or []}
    matched = []
    for mod in installed:
        if not mod.get("enabled") or mod.get("protected"):
            continue
        filename = (mod.get("filename") or "").lower()
        stem = (mod.get("stem") or "").lower()
        slug = str(mod.get("slug") or "").lower()
        project = str(mod.get("project_id") or "").lower()
        candidates = {stem, slug, project}
        # Metadata ids are the authoritative match when available.
        try:
            from . import mods as _mods
            meta = _mods.read_mod_metadata(
                os.path.join(_mods.get_profile_dir(mc_version, loader, version_id),
                             mod.get("filename") or ""), loader) or {}
            if meta.get("id"):
                candidates.add(str(meta["id"]).lower())
            if meta.get("name"):
                candidates.add(str(meta["name"]).lower().replace(" ", "-"))
        except Exception:
            pass
        if candidates & wanted or any(
                token and (token in stem or stem in token) for token in wanted):
            matched.append(mod)
    return matched


def _disable_mods(mc_version, loader, version_id, mods_to_disable) -> list[str]:
    fixed = []
    try:
        from . import mods as _mods
    except Exception:
        return fixed
    for mod in mods_to_disable:
        filename = mod.get("filename")
        if not filename:
            continue
        try:
            _mods.toggle_mod(mc_version, loader, filename, version_id=version_id)
        except Exception:
            log.info("crash doctor could not disable %s", filename, exc_info=True)
            continue
        profile = _mods.get_profile_dir(mc_version, loader, version_id)
        if not os.path.isfile(os.path.join(profile, filename)):
            fixed.append(mod.get("display_name") or filename)
    return fixed


def repair(mc_version: str | None = None, loader: str | None = None, *,
           version_id: str | None = None, text: str | None = None,
           path: str | None = None, after: float | None = None,
           status_cb=None, approve_cb=None, allow_online: bool = True,
           config: dict | None = None) -> dict:
    """Diagnose the newest crash and apply the verified repairs it implies.

    ``text`` overrides log discovery (tests / the in-memory tail of the crash
    that just happened). ``approve_cb`` is consulted for destructive mod
    changes exactly like the doctor's; pass ``lambda change: True`` from an
    explicit "Fix crash" click. Returns::

        {"log_path", "signature", "cause", "confidence", "evidence", "mods",
         "fixed": [str], "unfixed": [str], "changes": [...],
         "report": <mod_doctor report or None>, "recognised": bool}

    Never raises.
    """
    result = {
        "log_path": path,
        "signature": "unknown",
        "cause": "No crash log was found.",
        "confidence": 0.0,
        "evidence": "",
        "mods": [],
        "fixed": [],
        "unfixed": [],
        "changes": [],
        "report": None,
        "recognised": False,
    }
    try:
        if text is None:
            found_path, found_text = latest_crash_log(after=after)
            path = path or found_path
            text = found_text
        result["log_path"] = path
        if not (text or "").strip():
            result["unfixed"].append("no crash log was found - launch the game once more so Cubeon can read what happened")
            return result

        diagnosis = classify(text)
        result.update({
            "signature": diagnosis["signature"],
            "cause": diagnosis["cause"],
            "confidence": diagnosis["confidence"],
            "evidence": diagnosis["evidence"],
            "mods": diagnosis["mods"],
            "recognised": diagnosis["recognised"],
        })
        signature = diagnosis["signature"]

        def say(message):
            if status_cb:
                try:
                    status_cb(message)
                except Exception:
                    pass

        if signature == "out-of-memory":
            say("Raising the game's RAM…")
            outcome = _fix_memory(mc_version)
            (result["fixed"] if outcome.get("fixed") else result["unfixed"]).append(outcome["detail"])
        elif signature == "wrong-java":
            say("Fixing the Java runtime…")
            outcome = _fix_java(mc_version, version_id)
            (result["fixed"] if outcome.get("fixed") else result["unfixed"]).append(outcome["detail"])
        elif signature in ("bad-jvm-option", "java-missing"):
            say("Clearing the JVM option Java rejected…")
            outcome = _fix_jvm_flags(text)
            (result["fixed"] if outcome.get("fixed") else result["unfixed"]).append(outcome["detail"])
        elif signature == "corrupt-jar":
            say("Disabling the corrupt mod…")
            names = diagnosis["mods"]
            matched = _match_installed_mods(mc_version, loader, version_id, names)
            disabled = _disable_mods(mc_version, loader, version_id, matched)
            if disabled:
                result["fixed"].append("disabled corrupt mod(s): " + ", ".join(disabled))
            else:
                result["unfixed"].append(
                    "a corrupt mod jar was named in the log but Cubeon could "
                    "not match it to an installed file")
        elif signature in MOD_SIGNATURES:
            say("Checking mod dependencies and conflicts…")
            if not mc_version or not loader:
                result["unfixed"].append("the instance's Minecraft version/loader is unknown")
            else:
                try:
                    from . import mods as _mods
                    report = _mods.mod_doctor(
                        mc_version, loader, auto_fix=True,
                        check_online=allow_online, approve_cb=approve_cb,
                        version_id=version_id)
                    result["report"] = report
                    result["changes"] = report.get("changes") or []
                    for problem in report.get("fixed") or []:
                        result["fixed"].append(
                            f"{problem.get('mod') or 'mod'}: "
                            f"{problem.get('fix') or 'fixed'}")
                    for problem in report.get("unfixed") or []:
                        if problem.get("kind") in (
                                "verification-unavailable", "loader-version"):
                            continue
                        result["unfixed"].append(
                            f"{problem.get('mod') or 'mod'}: "
                            f"{problem.get('detail') or 'needs attention'}")
                except Exception:
                    log.warning("crash doctor mod pass failed", exc_info=True)
                    result["unfixed"].append("the mod check could not finish")
        elif signature == "graphics-driver":
            result["unfixed"].append(
                "this is a graphics-driver crash, not a mod problem - update "
                "the GPU driver or try the game's own OpenGL compatibility mode")
        elif signature == "incomplete-install":
            result["unfixed"].append(
                "this instance's Minecraft files are incomplete - reinstall "
                "the version from the Play tab")
        elif signature == "corrupt-world":
            result["unfixed"].append(
                "a world or datapack is corrupt - remove the named world/pack "
                "or restore a backup")
        else:
            result["unfixed"].append(
                "Cubeon couldn't identify this crash from the log - the "
                "evidence below is what the game reported")
        return result
    except Exception:
        log.warning("crash doctor failed", exc_info=True)
        result["unfixed"].append("the crash check itself failed; the log is still available")
        return result


def repair_plan(diagnosis: dict) -> list[str]:
    """Short human-readable actions implied by a diagnosis (UI helper)."""
    signature = (diagnosis or {}).get("signature")
    if signature == "out-of-memory":
        return ["Raise the game's RAM allocation"]
    if signature == "wrong-java":
        return ["Switch to a Java runtime this Minecraft version supports"]
    if signature in ("bad-jvm-option", "java-missing"):
        return ["Remove the JVM option Java rejected", "Re-check the Java path"]
    if signature == "duplicate-mods":
        return ["Disable extra copies of the same mod (files are kept)"]
    if signature == "missing-dependency":
        return ["Install the missing required dependency"]
    if signature in ("incompatible-mods", "mod-conflict"):
        return ["Replace or disable the incompatible mod build (files are kept)"]
    if signature == "corrupt-jar":
        return ["Disable the corrupt mod jar (the file is kept)"]
    if signature == "graphics-driver":
        return ["Update the GPU driver - this is not a mod problem"]
    if signature == "incomplete-install":
        return ["Reinstall this Minecraft version"]
    if signature == "corrupt-world":
        return ["Remove the corrupt world or datapack"]
    return ["Show the crash evidence to support"]
