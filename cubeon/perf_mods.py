"""
Client performance add-ons for the Cubeon Client.

The Cubeon Client itself is a social mod: it draws a small name badge and opens
the Friends screen. It is deliberately cheap, which also means it does not make
Minecraft render any faster - so "activate Cubeon Client" would otherwise get
the button and nothing else. This module closes that gap: while the client mod
is on, it makes sure a hand-picked set of client-side performance mods is
installed in the same (mc_version, loader) profile.

This is deliberately wider than "Sodium + Lithium". Those two move raw frame
rate, but they are not the whole story FastClient-style clients sell: on a
CPU-bound machine (which every Minecraft client eventually is) the wins that
turn a 40 FPS busy server into a smooth 100+ are mostly in *culling* and
*per-frame overhead*:

  - **Sodium** - replaces the terrain/entity renderer. The single biggest
    client FPS win on every GPU.
  - **Lithium** - optimises game-logic ticking (mob AI, block updates, entity
    handling), which keeps the frame rate high in a busy world.
  - **ImmediatelyFast** - fixes immediate-mode rendering (HUD, entities,
    text) which is otherwise a per-frame CPU cost Sodium cannot touch.
  - **EntityCulling** - skips entities hidden behind geometry entirely.
  - **MoreCulling** - culls block/leaf/glass faces the vanilla renderer still
    submits.
  - **BadOptimizations** - a grab-bag of safe micro-optimisations in the
    render/light paths.
  - **Krypton** - moves networking off the render thread.
  - **ThreadTweak** - adjusts client/server thread scheduling priorities.
  - **Dynamic FPS** - drops frame rate while the window is unfocused.

All are fetched from Modrinth exactly like a mod the user picked themselves:
matched to the profile's Minecraft version and loader, stored in the profile
folder, and skipped when they are already present (including a manual install).
The launcher's normal mod sync then carries them into the game.

Best-effort by design, because this runs inside the launch path: no build for
this Minecraft version, a dead network, or a jar the user manages by hand all
just mean the boost is smaller. Nothing here can stop the game from starting.
"""
from .mod_loaders import MOD_CAPABLE_LOADERS
from .mods import download_mod, get_mod_download, list_mods, name_stem

# (Modrinth slug, Modrinth project id, display label), in install order.
# Sodium/Lithium stay first because they are the load-bearing pair - if a
# download runs out of time, the two mods that actually replace the renderer
# and ticker landed first. Pure client FPS; nothing here changes gameplay.
PERF_MODS = (
    ("sodium", "AANobbMI", "Sodium"),
    ("lithium", "gvQqBUqZ", "Lithium"),
    ("immediatelyfast", "5ZwdcRci", "ImmediatelyFast"),
    ("entityculling", "NNAgCjsB", "EntityCulling"),
    ("moreculling", "51shyZVL", "MoreCulling"),
    ("badoptimizations", "g96Z4WVZ", "BadOptimizations"),
    ("krypton", "fQEb0iXm", "Krypton"),
    ("threadtweak", "vSEH1ERy", "ThreadTweak"),
    ("dynamic-fps", "LQ3K71Q1", "Dynamic FPS"),
)

# Kept as its own name: tests and callers refer to the slug tuple.
PERF_MOD_SLUGS = tuple(slug for slug, _pid, _label in PERF_MODS)

_LABELS = {slug: label for slug, _pid, label in PERF_MODS}


def _present(mc_version: str | None, loader: str | None) -> set:
    """The performance mods already in this profile, by slug.

    Matches the recorded Modrinth slug, the display name, the project id and
    the filename, so a jar the user dropped in by hand still counts - a second
    copy of Sodium is a duplicate-mod crash, not a boost."""
    found: set = set()
    if not mc_version or loader not in MOD_CAPABLE_LOADERS:
        return found
    try:
        mods = list_mods(mc_version, loader)
    except Exception:
        return found
    for mod in mods:
        identities = {str(mod.get(key) or "").lower()
                      for key in ("slug", "display_name", "project_id")}
        identities.add(name_stem(mod.get("filename") or ""))
        for slug, project_id, _label in PERF_MODS:
            if slug in identities or project_id.lower() in identities:
                found.add(slug)
    return found


def is_installed(mc_version: str | None, loader: str | None) -> bool:
    """True when every performance mod is already in the profile."""
    if not mc_version or loader not in MOD_CAPABLE_LOADERS:
        return False
    return _present(mc_version, loader) >= set(PERF_MOD_SLUGS)


def ensure_installed(mc_version: str | None, loader: str | None,
                     status_cb=None) -> dict:
    """Installs any missing performance mod into the profile.

    Returns {"installed", "kept", "failed", "detail"} so the caller can log or
    show what actually happened. Never raises: every failure is reported as a
    slug in "failed" and the launch continues.
    """
    result = {"installed": [], "kept": [], "failed": [], "detail": ""}

    if not mc_version:
        result["detail"] = "no Minecraft version selected"
        return result
    if loader not in ("fabric", "quilt"):
        # These mods ship as Fabric mods; Forge/NeoForge/vanilla have no
        # compatible build to fetch, so there is nothing to pretend about.
        result["detail"] = "performance mods need a Fabric or Quilt profile"
        return result

    present = _present(mc_version, loader)
    for slug, project_id, label in PERF_MODS:
        if slug in present:
            result["kept"].append(slug)
            continue
        try:
            file_info = get_mod_download(slug, mc_version=mc_version, loader=loader)
            if not file_info:
                result["failed"].append(slug)
                continue
            if status_cb:
                status_cb(f"Installing {label}")
            download_mod(
                file_info["url"], file_info["filename"],
                slug=slug, project_id=project_id,
                mc_version=mc_version, loader=loader,
                hashes=file_info.get("hashes"),
            )
            result["installed"].append(slug)
        except Exception:
            # Network, disk, a version with no build - all the same answer:
            # the boost is smaller, the game still launches.
            result["failed"].append(slug)

    parts = []
    if result["installed"]:
        parts.append("installed " + ", ".join(
            _LABELS.get(s, s) for s in result["installed"]))
    if result["kept"]:
        parts.append("already had " + ", ".join(
            _LABELS.get(s, s) for s in result["kept"]))
    if result["failed"]:
        parts.append("couldn't get " + ", ".join(
            _LABELS.get(s, s) for s in result["failed"]))
    result["detail"] = "; ".join(parts)
    return result
