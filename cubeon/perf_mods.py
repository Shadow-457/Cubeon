"""
Client performance add-ons for the Cubeon Client.

The Cubeon Client itself is a social mod: it draws a small name badge and opens
the Friends screen. It is deliberately cheap, which also means it does not make
Minecraft render any faster - so "activate Cubeon Client" would otherwise get
the button and nothing else. This module closes that gap: while the client mod
is on, it makes sure the two mods that actually move frame rate are installed
in the same (mc_version, loader) profile:

  - **Sodium** replaces the terrain/entity renderer. It is the single biggest
    client FPS win on every GPU, and the one that turns a 70 FPS machine into
    several hundred.
  - **Lithium** optimises game-logic ticking (mob AI, block updates, entity
    handling), which is what keeps that frame rate high in a busy world.

They are fetched from Modrinth exactly like a mod the user picked themselves:
matched to the profile's Minecraft version and loader, stored in the profile
folder, and skipped when they are already present (including a manual install).
The launcher's normal mod sync then carries them into the game.

Best-effort by design, because this runs inside the launch path: no build for
this Minecraft version, a dead network, or a jar the user manages by hand all
just mean the boost is unchanged. Nothing here can stop the game from starting.
"""
from .mod_loaders import MOD_CAPABLE_LOADERS
from .mods import download_mod, get_mod_download, list_mods

# Modrinth slugs, in install order. Chosen for pure client FPS: Sodium is
# rendering, Lithium is tick logic. Nothing here changes gameplay.
PERF_MOD_SLUGS = ("sodium", "lithium")

# What the user sees when the boost is being prepared. Kept short - it shares
# the launch status line with mod and skin setup.
_LABELS = {"sodium": "Sodium", "lithium": "Lithium"}


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
        blob = " ".join(
            str(mod.get(key) or "")
            for key in ("slug", "display_name", "project_id", "filename")
        ).lower()
        for slug in PERF_MOD_SLUGS:
            if slug in blob:
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
        # The two mods ship as Fabric mods; Forge/NeoForge/vanilla have no
        # compatible build to fetch, so there is nothing to pretend about.
        result["detail"] = "performance mods need a Fabric or Quilt profile"
        return result

    present = _present(mc_version, loader)
    for slug in PERF_MOD_SLUGS:
        if slug in present:
            result["kept"].append(slug)
            continue
        try:
            file_info = get_mod_download(slug, mc_version=mc_version, loader=loader)
            if not file_info:
                result["failed"].append(slug)
                continue
            if status_cb:
                status_cb(f"Installing {_LABELS.get(slug, slug)}")
            download_mod(
                file_info["url"], file_info["filename"],
                slug=slug, mc_version=mc_version, loader=loader,
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
