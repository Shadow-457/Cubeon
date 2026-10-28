"""Installed-instance metadata for the Play tab.

The Play tab used to answer "what loader is this? how many mods? how big?
when did I last play it?" from three unrelated places at once: the version
dropdown's option text, ``state["installed_meta"]``, and ad-hoc id parsing
inline in ``main.py``. None of them could answer all four, so the Play tab's
instance panel had nothing to render.

This module is the single source of truth for that. It is pure data - no
Flet - so it is trivially unit-testable and the UI module (``ui/versions.py``)
only has to render the dicts.

What it reads (all best-effort; every path degrades to a sensible default
rather than raising into the UI):
  * ``versions.get_installed_versions()`` for the set of installs,
  * each install's id/folder for the loader tag,
  * the shared ``(mc_version, loader)`` mod profile for the mod count,
  * the install's own folder for the on-disk size,
  * a tiny ``instance_play.json`` sidecar for "last played".

The size walk is deliberately NOT part of ``describe()``: it is the one
expensive call here (a full recursive stat of a version folder - thousands
of files), and the Play tab rebuilds its list on the event loop. Callers
that want it (the Instances manager) ask for it explicitly and off-thread
via ``instance_size_bytes``.
"""
import json
import os
import re
import threading
import time

from .paths import CUBEON_HOME

# The loader a version id/folder encodes. "vanilla" is the absence of a
# loader token, not a claim about what the install actually runs - the id is
# the only thing a folder gives us, and it is what every other part of the
# launcher keys off too (see versions.suggest_friendly_name).
LOADER_LABELS = {
    "vanilla": "Vanilla",
    "fabric": "Fabric",
    "quilt": "Quilt",
    "forge": "Forge",
    "neoforge": "NeoForge",
    "optifine": "OptiFine",
}

# Loaders whose (mc_version, loader) profile can actually hold mods. Mirrors
# mod_loaders.MOD_CAPABLE_LOADERS; kept local so this module never imports
# the loader stack just to count mods.
MOD_CAPABLE = ("fabric", "quilt", "forge", "neoforge")

# Newest/longest token first: "forge" must never match inside "neoforge".
_TOKEN_ORDER = ("neoforge", "fabric", "quilt", "forge", "optifine")

_PLAY_STORE = os.path.join(CUBEON_HOME, "instance_play.json")
# mark_played/forget_played are read-modify-write cycles on one file: two
# launches at once (or a launch during a delete) must not lose an entry.
_PLAY_STORE_LOCK = threading.Lock()


def detect_loader(version_id: "str | None", folder: "str | None" = None) -> str:
    """The loader key encoded in an install id/folder.

    Whole-word match (not substring) so "forge" does not false-match an id
    that contains "neoforge" - the exact trap ``find_installed_loader_version``
    documents. Returns ``"vanilla"`` when nothing matches, which is what the
    rest of the launcher means by "no loader".
    """
    hay = f"{version_id or ''} {folder or ''}".lower()
    for key in _TOKEN_ORDER:
        if re.search(rf"(?<![a-z]){re.escape(key)}(?![a-z])", hay):
            return key
    return "vanilla"


def loader_label(loader_key: "str | None") -> str:
    return LOADER_LABELS.get(loader_key or "vanilla", "Vanilla")


def format_size(num_bytes: "int | float | None") -> str:
    """Human-readable size ("1.2 GB"). Empty string for None/negative."""
    if num_bytes is None or num_bytes < 0:
        return ""
    n = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(n)} B"
            return f"{n:.1f} {unit}" if n < 100 else f"{n:.0f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TB"


def instance_size_bytes(version_id: str, folder: "str | None" = None,
                        *, _versions_dir: "str | None" = None) -> "int | None":
    """Recursive on-disk size of one install's folder, or None.

    Expensive - a full stat walk - so only call it off the event loop (the
    Instances manager does). Never raises.
    """
    if _versions_dir is None:
        from .paths import MINECRAFT_DIR
        _versions_dir = os.path.join(MINECRAFT_DIR, "versions")
    root = os.path.join(_versions_dir, folder or version_id)
    if not os.path.isdir(root):
        return None
    total = 0
    try:
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, name))
                except OSError:
                    continue
    except OSError:
        return None
    return total


def mod_count(mc_version: "str | None", loader: "str | None",
              version_id: "str | None" = None) -> int:
    """How many mods this instance's profile holds.

    Deliberately NOT ``len(list_mods(...))``. That reads a ``.cubeon.json``
    sidecar and stats every jar, so on a 300-mod pack it costs ~50 ms - and
    ``describe()`` is called once per row on every Play-tab repaint. The rows
    only need the count, so this does one
    ``scandir`` and no per-file opens: the same answer in ~0.3 ms. The filter
    matches ``list_mods`` exactly (``.jar`` / ``.jar.disabled`` regular files;
    sidecars and ``_profile.json`` are not jars).

    Zero for vanilla / a missing profile, and never raises - the count is
    decoration, not a reason to fail a repaint.
    """
    if not mc_version or loader not in MOD_CAPABLE:
        return 0
    try:
        from .mods import resolve_profile_dir
        profile_dir = resolve_profile_dir(mc_version, loader, version_id)
        if not os.path.isdir(profile_dir):
            return 0
        total = 0
        with os.scandir(profile_dir) as entries:
            for entry in entries:
                name = entry.name
                if not (name.endswith(".jar") or name.endswith(".jar.disabled")):
                    continue
                try:
                    if entry.is_file():
                        total += 1
                except OSError:
                    continue
        return total
    except Exception:
        return 0


# ---------------------------------------------------------------- last played ---
# A launch writes {version_id: epoch}. Kept out of config.json on purpose:
# it changes on every launch and would otherwise churn the most frequently
# written file in the launcher for a purely cosmetic "last played" label.
def _read_play_store() -> dict:
    try:
        with open(_PLAY_STORE, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            # bool is an int subclass; `true` is not a timestamp.
            return {k: float(v) for k, v in data.items()
                    if isinstance(k, str) and isinstance(v, (int, float))
                    and not isinstance(v, bool)}
    except (OSError, ValueError):
        pass
    return {}


def play_store() -> dict:
    """A snapshot of the last-played sidecar ({version_id: epoch}).

    Public so a caller rendering several instances (the version panel)
    reads the file ONCE and passes it to every ``describe(..., play_store=)``
    instead of re-opening it per row. Never raises; a missing/corrupt file is
    an empty map.
    """
    return _read_play_store()


def mark_played(version_id: "str | None", when: "float | None" = None) -> None:
    """Record that ``version_id`` was just launched. Never raises."""
    if not version_id:
        return
    try:
        with _PLAY_STORE_LOCK:
            store = _read_play_store()
            store[version_id] = float(when if when is not None else time.time())
            # Keep the file small: only the 50 most recent installs matter, and a
            # deleted/reinstalled version is forgotten by list_installed anyway.
            if len(store) > 50:
                for vid, _ in sorted(store.items(), key=lambda kv: kv[1])[:-50]:
                    store.pop(vid, None)
            os.makedirs(os.path.dirname(_PLAY_STORE), exist_ok=True)
            tmp = f"{_PLAY_STORE}.{os.getpid()}.{threading.get_ident()}.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(store, fh)
            os.replace(tmp, _PLAY_STORE)
    except OSError:
        pass


def forget_played(version_id: "str | None") -> None:
    """Drop a deleted instance's `last played` entry. Never raises.

    Without this, deleting and reinstalling the same id resurrects the old
    "played 2 days ago" label - the store is keyed by version id, and
    `mark_played` only trims itself after 50 entries.
    """
    if not version_id:
        return
    try:
        with _PLAY_STORE_LOCK:
            store = _read_play_store()
            if store.pop(version_id, None) is None:
                return
            os.makedirs(os.path.dirname(_PLAY_STORE), exist_ok=True)
            tmp = f"{_PLAY_STORE}.{os.getpid()}.{threading.get_ident()}.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(store, fh)
            os.replace(tmp, _PLAY_STORE)
    except OSError:
        pass


def last_played(version_id: "str | None", store: "dict | None" = None) -> "float | None":
    if not version_id:
        return None
    store = _read_play_store() if store is None else store
    return store.get(version_id)


def relative_time(when: "float | None", *, now: "float | None" = None) -> str:
    """'just now' / '2h ago' / '3d ago' / '' for None. Cosmetic."""
    if not when:
        return ""
    delta = max(0.0, (now if now is not None else time.time()) - when)
    if delta < 90:
        return "just now"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    if delta < 86400 * 30:
        return f"{int(delta // 86400)}d ago"
    return time.strftime("%b %d", time.localtime(when))


# ------------------------------------------------------------------- describe ---
def describe(version_id: str, meta: "dict | None" = None,
             label: "str | None" = None, *, play_store: "dict | None" = None,
             with_mods: bool = True) -> dict:
    """One installed instance as a flat dict the UI can render directly.

    ``meta`` is the entry from ``versions.get_installed_versions()`` (it
    carries ``display_name`` / ``incomplete`` / ``issue``). ``label`` is the
    user's nickname from ``cfg["version_labels"]``, which wins over the
    auto display name. Never raises.
    """
    from .versions import extract_mc_version

    meta = meta or {}
    sidecar = {}
    try:
        from .mods import read_instance_meta
        sidecar = read_instance_meta(version_id) or {}
    except Exception:
        sidecar = {}
    try:
        base = sidecar.get("mc_version") or extract_mc_version(version_id) or version_id
    except Exception:
        base = sidecar.get("mc_version") or version_id
    loader = detect_loader(version_id, meta.get("folder"))
    recorded_loader = sidecar.get("loader")
    if recorded_loader in MOD_CAPABLE or recorded_loader == "vanilla":
        loader = recorded_loader
    display_name = label or sidecar.get("name") or meta.get("display_name") or version_id
    return {
        "id": version_id,
        "base_version": base,
        "loader": loader,
        "loader_label": loader_label(loader),
        "display_name": display_name,
        "folder": meta.get("folder") or version_id,
        "incomplete": bool(meta.get("incomplete")),
        "issue": meta.get("issue") or "",
        "mod_count": mod_count(base, loader, version_id) if with_mods else 0,
        "last_played": last_played(version_id, play_store),
        "profile": sidecar.get("profile") or "",
        "is_instance": bool(sidecar),
    }


def list_installed(installed: "list[dict] | None" = None,
                   labels: "dict | None" = None, *,
                   with_mods: bool = True) -> "list[dict]":
    """Every installed version, described, newest game version first.

    ``installed`` defaults to a fresh scan; pass the already-scanned list to
    avoid a second directory walk on a repaint. Order follows the scan (which
    already sorts newest-first), so this is stable across calls.

    Build inputs of an installed modpack (the vanilla jar and the bare loader
    profile the pack's private clone was built from) are skipped: one pack is
    ONE instance in this list, not three. They still exist on disk and stay
    selectable elsewhere - this is a display filter, not a deletion.
    """
    if installed is None:
        from .versions import get_installed_versions
        installed = get_installed_versions()
    labels = labels or {}
    play_store = _read_play_store()
    hidden = _hidden_build_sources(installed)
    out = []
    for v in installed:
        vid = v.get("id")
        if not vid:
            continue
        if vid in hidden and not labels.get(vid):
            # A labelled install is the user's own; never hide it even if a
            # pack happened to be built from the same folder.
            continue
        out.append(describe(vid, v, labels.get(vid),
                            play_store=play_store, with_mods=with_mods))
    return out


def _hidden_build_sources(installed: "list[dict]") -> "set[str]":
    """Version ids that exist only as inputs to an installed modpack.

    New installs record ``built_from`` in the pack instance's sidecar (the
    vanilla + loader folders THIS install created). Installs made before that
    field existed are inferred from the pack's sidecar: an isolated pack owns
    a clone, so the loader build it was cloned from - and the vanilla jar it
    needs - are not separate instances. A version that has its own sidecar or
    a user label is never treated as a build input (see ``list_installed``).
    """
    try:
        from .mods import read_instance_meta, profile_key
        from .mod_loaders import find_installed_loader_version
    except Exception:
        return set()
    ids = {v.get("id") for v in installed if v.get("id")}
    metas: dict[str, dict] = {}
    for vid in ids:
        try:
            metas[vid] = read_instance_meta(vid) or {}
        except Exception:
            metas[vid] = {}
    # A version with its own sidecar is an instance, never a build input.
    plain_ids = {vid for vid, meta in metas.items() if not meta}
    hidden: set[str] = set()
    for vid, meta in metas.items():
        if not meta:
            continue
        for src in meta.get("built_from") or ():
            if isinstance(src, str) and src and src != vid:
                hidden.add(src)
        if not (meta.get("pack_version") or meta.get("pack")):
            continue
        # Legacy isolated pack: no built_from list, so derive the clone source.
        try:
            legacy = profile_key(meta.get("mc_version"), meta.get("loader"))
        except Exception:
            legacy = None
        if not legacy or meta.get("profile") == legacy:
            continue  # the pack itself is the shared loader install
        loader_src = None
        try:
            loader_src = find_installed_loader_version(
                plain_ids, meta.get("loader"), meta.get("mc_version"))
        except Exception:
            loader_src = None
        if loader_src and loader_src != vid:
            hidden.add(loader_src)
        base = meta.get("mc_version")
        if base and base in ids and base not in (vid, loader_src):
            hidden.add(base)
    return hidden
