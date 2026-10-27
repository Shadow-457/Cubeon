"""Minimal crash explanation and repair for the Play card's **Fix crash**.

Three steps, no separate diagnosis engine:

1. Read the newest crash evidence (``crash-reports/*.txt`` first, then
   ``logs/latest.log``, then Cubeon's own game-session logs).
2. Say what happened in one sentence and what to do next.
3. Run the existing content checks that can actually fix it: mod
   dependencies / duplicates / conflicts / wrong loader or version, and the
   launch config (invalid JVM flags, missing Java path). A memory crash gets
   a RAM bump instead.

Everything is evidence-first and never raises. Mod changes are the doctor's
usual reversible disable-not-delete / replace path, and clicking Fix crash is
the consent for them.
"""
from __future__ import annotations

import os
import re

MAX_READ = 200_000
EVIDENCE_CHARS = 2_000

_MARKERS = (
    "exception", "error", "caused by", "failed", "missing", "requires",
    "incompatible", "duplicate", "outofmemory", "unrecognized", "unsupported",
    "corrupt", "glfw", "mixin", "java", "mod",
)

_RULES = (
    ("memory", (
        r"outofmemoryerror", r"java heap space", r"gc overhead limit",
        r"unable to allocate", r"not enough memory",
    ), "Minecraft ran out of memory.",
       "Cubeon can raise the game's RAM for you; if it still happens, close "
       "other apps and lower render distance."),
    ("java", (
        r"unsupportedclassversionerror", r"class file version",
        r"requires (?:java|jdk)", r"java \d+.* required",
        r"wrong version of java", r"no java runtime",
    ), "Minecraft is running on the wrong Java version.",
       "Install Java 21 and pick it in Settings \u2192 Java, then launch again."),
    ("jvm", (
        r"unrecognized (?:vm )?option", r"could not create the java virtual machine",
        r"could not find or load main class", r"invalid maximum heap size",
        r"invalid initial heap size",
    ), "A custom JVM option is invalid, so Java refused to start.",
       "Clear the custom JVM flags in Settings \u2192 Java (Cubeon removes the "
       "ones Java rejected)."),
    ("mods", (
        r"incompatible mod set", r"mod resolution", r"duplicate mod",
        r"found duplicate", r"missing or unsupported mandatory dependenc",
        r"requires .* which is missing", r"mod id:",
        r"invalid or corrupted jarfile", r"invalid loc header",
        r"error in opening zip file", r"mixin apply failed",
        r"mixin.*(?:failed|exception)", r"injectionerror",
        r"nosuchmethoderror", r"abstractmethoderror", r"illegalaccesserror",
        r"classnotfoundexception",
    ), "A mod is missing a dependency or conflicts with another mod.",
       "Cubeon disables or replaces only the mods the log implicates; the old "
       "files are kept, so you can re-enable them in Mods \u2192 Installed."),
    ("graphics", (
        r"pixel format not accelerated", r"failed to create window", r"glfw",
        r"opengl", r"org\.lwjgl", r"wgpu", r"vulkan",
    ), "The graphics driver rejected Minecraft's window.",
       "Update your GPU driver and close other games or overlays, then try "
       "again."),
)


def _recent_files(directory: str, suffixes: tuple[str, ...]) -> list[str]:
    try:
        entries = [entry for entry in os.scandir(directory) if entry.is_file()
                   and entry.name.lower().endswith(suffixes)]
    except OSError:
        return []

    def _mtime(entry):
        try:
            return entry.stat().st_mtime
        except OSError:
            return 0.0

    entries.sort(key=_mtime, reverse=True)
    return [entry.path for entry in entries]


def _read_tail(path: str) -> str:
    try:
        with open(path, "rb") as fh:
            try:
                fh.seek(-MAX_READ, os.SEEK_END)
            except OSError:
                fh.seek(0)
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return ""


def log_candidates() -> list[str]:
    """Crash evidence paths, newest and most specific first."""
    from .paths import CUBEON_HOME, MINECRAFT_DIR
    out = _recent_files(os.path.join(MINECRAFT_DIR, "crash-reports"), (".txt",))
    latest = os.path.join(MINECRAFT_DIR, "logs", "latest.log")
    if os.path.isfile(latest):
        out.append(latest)
    out.extend(_recent_files(CUBEON_HOME, (".log",)))
    seen, unique = set(), []
    for path in out:
        real = os.path.abspath(path)
        if real not in seen:
            seen.add(real)
            unique.append(path)
    return unique


def latest_log(*, after: float | None = None) -> tuple[str | None, str]:
    """The newest crash evidence and its text, or ``(None, "")``."""
    for path in log_candidates():
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
    lines = text.splitlines()
    picked = []
    for index, line in enumerate(lines):
        low = line.lower()
        if any(marker in low for marker in _MARKERS):
            picked.extend(lines[max(0, index - 1):index + 3])
            if len(picked) >= 12:
                break
    return ("\n".join(picked) or "\n".join(lines[-10:]))[:EVIDENCE_CHARS]


def explain(text: str) -> dict:
    """Name the cause in plain language. Never raises."""
    low = (text or "").lower()
    for kind, patterns, cause, advice in _RULES:
        if any(re.search(pattern, low) for pattern in patterns):
            return {"kind": kind, "cause": cause, "advice": advice,
                    "evidence": _evidence(text or "")}
    if not (text or "").strip():
        return {"kind": "none", "cause": "No crash log was found.",
                "advice": "Launch the game once more so Cubeon can read what "
                          "happened.", "evidence": ""}
    return {
        "kind": "unknown",
        "cause": "Minecraft crashed, but the log doesn't name a known cause.",
        "advice": "Cubeon checked the mod set and launch settings. If it "
                  "still crashes, update the pack or share the log on Discord.",
        "evidence": _evidence(text),
    }


def _raise_ram() -> str | None:
    try:
        from .config import (get_system_ram_mb, load_config,
                             recommended_max_ram_mb, save_config)
        cfg = load_config() or {}
        current = int(cfg.get("ram_mb") or 4096)
        system = int(get_system_ram_mb())
        recommended = int(recommended_max_ram_mb(system))
        spare = max(system - 2048, 4096)
        target = min(max(current + 2048, 4096), max(recommended, 6144),
                     spare, 8192)
        target = int(target // 512 * 512)
        if target <= current:
            return None
        cfg["ram_mb"] = target
        save_config(cfg)
        if int((load_config() or {}).get("ram_mb") or 0) != target:
            return None
        return f"Raised the game's RAM from {current} MB to {target} MB."
    except Exception:
        return None


def _doctor(mc_version, loader, version_id, include, check_online, status_cb):
    try:
        from .doctor import run_doctor
        return run_doctor(
            mc_version, loader, auto_fix=True, check_online=check_online,
            version_id=version_id, include=include, status_cb=status_cb,
            approve_cb=lambda change: True)
    except Exception:
        return None


def _disable_corrupt(text: str, mc_version, loader,
                     version_id) -> str | None:
    """Rename the jar named by a corrupt-zip line; never delete it."""
    lines = [line for line in (text or "").splitlines()
             if re.search(r"(?i)invalid or corrupted jarfile|invalid loc header|"
                          r"error in opening zip file", line)]
    names = []
    for line in lines:
        names.extend(re.findall(r"([A-Za-z0-9._+\-]+\.jar)", line))
    if not names:
        return None
    try:
        from . import mods
        for name in names:
            try:
                mods.toggle_mod(mc_version, loader, name,
                                version_id=version_id)
            except Exception:
                continue  # missing/protected: try the next name in the log
            return (f"Disabled the corrupt jar {name} "
                    f"(kept as {name}.disabled).")
        return None
    except Exception:
        return None


def _remove_jvm_option(text: str) -> str | None:
    """Drop the exact option Java named as unrecognized, keeping the rest."""
    match = re.search(r"(?i)unrecognized (?:vm )?option\s*:\s*(\S+)",
                      text or "")
    if not match:
        return None
    token = match.group(1).strip().strip("'\"")
    try:
        from .config import load_config, save_config
        from .launch import _parse_custom_jvm_flags
        cfg = load_config() or {}
        raw = cfg.get("custom_jvm_flags") or ""
        tokens = _parse_custom_jvm_flags(raw)
        keep = [item for item in tokens if item != token]
        if keep == tokens:
            return None
        cfg["custom_jvm_flags"] = " ".join(keep)
        save_config(cfg)
        return f"Removed the JVM option {token} that Java rejected."
    except Exception:
        return None


def _merge_report(result: dict, report: dict | None) -> None:
    if not report:
        return
    result["report"] = report
    for problem in report.get("fixed") or []:
        label = problem.get("item") or problem.get("mod") or "Content"
        detail = problem.get("fix") or problem.get("detail") or "fixed"
        result["fixed"].append(f"{label}: {detail}")
    for problem in report.get("unfixed") or []:
        if problem.get("kind") == "verification-unavailable":
            continue
        label = problem.get("item") or problem.get("mod") or "Content"
        detail = problem.get("detail") or "needs attention"
        result["unfixed"].append(f"{label}: {detail}")


def diagnose_and_fix(mc_version: str | None = None,
                     loader: str | None = None, *,
                     version_id: str | None = None,
                     text: str | None = None, path: str | None = None,
                     after: float | None = None,
                     allow_online: bool = True,
                     status_cb=None) -> dict:
    """Read the newest crash, explain it, and fix what the checks can fix.

    Returns ``{"log_path", "kind", "cause", "advice", "evidence",
    "fixed": [str], "unfixed": [str], "report": <doctor report or None>}``.
    Never raises.
    """
    result = {
        "log_path": path,
        "kind": "none",
        "cause": "No crash log was found.",
        "advice": "Launch the game once more so Cubeon can read what happened.",
        "evidence": "",
        "fixed": [],
        "unfixed": [],
        "report": None,
    }
    try:
        if text is None:
            found_path, found_text = latest_log(after=after)
            path = path or found_path
            text = found_text
        result["log_path"] = path
        if not (text or "").strip():
            return result

        info = explain(text)
        result.update({key: info[key] for key in
                       ("kind", "cause", "advice", "evidence")})
        if status_cb:
            status_cb(info["cause"])

        kind = info["kind"]
        if kind == "memory":
            raised = _raise_ram()
            if raised:
                result["fixed"].append(raised)
            else:
                result["unfixed"].append(info["advice"])
            return result

        if kind in ("java", "jvm"):
            # The launch section clears a missing java_path / non-flag token;
            # the option Java named as unrecognized is removed verbatim here
            # (a syntactically valid flag still fails if this JVM rejects it).
            if kind == "jvm":
                removed = _remove_jvm_option(text)
                if removed:
                    result["fixed"].append(removed)
            _merge_report(result, _doctor(
                mc_version, loader, version_id, ("launch",), False,
                status_cb))
            if not result["fixed"]:
                result["unfixed"].append(info["advice"])
            return result

        if kind == "graphics":
            # No content check can fix a driver rejection; the advice above is
            # the whole answer, and running the mod doctor would only churn.
            return result

        # Mod-set crash (or an unrecognised one): the only causes Cubeon can
        # repair are mods and launch config, so check both. Online lookups are
        # only worth the wait when the log actually points at mods.
        if status_cb:
            status_cb("Checking mod dependencies and conflicts\u2026")
        corrupt = _disable_corrupt(text, mc_version, loader, version_id)
        if corrupt:
            result["fixed"].append(corrupt)
        _merge_report(result, _doctor(
            mc_version, loader, version_id, ("mods", "launch"),
            allow_online and kind == "mods", status_cb))
        if not result["fixed"] and not result["unfixed"]:
            result["unfixed"].append(info["advice"])
        return result
    except Exception as error:  # a crash path must never break the launcher
        result["unfixed"].append(f"the crash check failed: {error}")
        return result
