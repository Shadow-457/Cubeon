"""
Resource pack and shader management: Modrinth search/download plus CRUD over
the two shared game folders (.minecraft/resourcepacks, .minecraft/shaderpacks).

--- Why this is deliberately simpler than mods.py ---

Mods are per-(version, loader): each combo gets its own profile folder, and
launch_game() has to sync the active profile's enabled jars into
MINECRAFT_DIR/mods every launch (see cubeon/mods.py for the bugs that caused).

Resource packs and shaders are NOT like that. Minecraft reads them straight
out of the single shared resourcepacks/ and shaderpacks/ folders no matter
which version launches, and the *game* decides which are actually applied
(via its own in-game menu / options.txt), not the launcher. So there are no
profiles here, no enable/disable-by-rename, and no sync step - dropping a
.zip into the right folder is the whole install. That also means these are
version-agnostic: a pack installed once is visible to every version, exactly
like it is when you install one by hand.

Shaders additionally need Iris (Fabric) or OptiFine installed to have any
effect in-game, but the .zip still just lives in shaderpacks/ either way, so
that's the mod-loader layer's concern, not this module's.
"""
import json
import os
import shutil
import uuid

from .paths import APP_NAME, RESOURCEPACKS_DIR, SHADERPACKS_DIR
from . import local_cache
from . import net
# Reuse the exact same Modrinth browse-sort / relevance-banding logic the Mods
# tab uses, so "browse" and search behave identically across content types
# instead of drifting into two subtly different rankings.
from .mods import MODRINTH_API, MODRINTH_HEADERS, modrinth_search_index, rank_search_hits


# Everything that differs between a resource pack and a shader, in one table,
# so every function below stays a single code path keyed by content_type
# instead of forking into near-duplicate resourcepack/shader variants.
#
#   dir          -> the shared game folder the file installs into
#   project_type -> Modrinth's own project_type facet value
#   exts         -> accepted local-file extensions (both ship as .zip)
#   categories   -> (facet_id, label) quick-filter chips for this type; the
#                   ids are real Modrinth category slugs for this project_type
CONTENT_TYPES = {
    "resourcepack": {
        "dir": RESOURCEPACKS_DIR,
        "project_type": "resourcepack",
        "label": "Resource pack",
        "label_plural": "Resource packs",
        "exts": (".zip",),
        "categories": [
            ("", "All"),
            ("realistic", "Realistic"),
            ("simplistic", "Simplistic"),
            ("vanilla-like", "Vanilla-like"),
            ("themed", "Themed"),
            ("decoration", "Decoration"),
            ("modded", "Modded"),
            ("utility", "Utility"),
        ],
    },
    "shader": {
        "dir": SHADERPACKS_DIR,
        "project_type": "shader",
        "label": "Shader",
        "label_plural": "Shaders",
        "exts": (".zip",),
        "categories": [
            ("", "All"),
            ("realistic", "Realistic"),
            ("semi-realistic", "Semi-realistic"),
            ("fantasy", "Fantasy"),
            ("vanilla-like", "Vanilla-like"),
            ("cartoon", "Cartoon"),
            ("atmosphere", "Atmosphere"),
            ("reflections", "Reflections"),
        ],
    },
}


def _cfg(content_type: str) -> dict:
    try:
        return CONTENT_TYPES[content_type]
    except KeyError:
        raise ValueError(f"Unknown content type: {content_type!r}") from None


def content_dir(content_type: str) -> str:
    """The shared game folder this content type installs into, created on
    demand so a fresh install (or a user who wiped .minecraft) never hits a
    missing-folder error on first use."""
    d = _cfg(content_type)["dir"]
    os.makedirs(d, exist_ok=True)
    return d


def category_choices(content_type: str) -> list:
    """(facet_id, label) pairs for this type's quick-filter chips."""
    return _cfg(content_type)["categories"]


# ---------------------------------------------------------------------------
# Installed-content CRUD (over the shared game folder - no profiles)
# ---------------------------------------------------------------------------

def list_content(content_type: str) -> list[dict]:
    """Every pack/shader currently installed for this type. Unlike mods there's
    no enabled/disabled state to track here - the game itself owns which packs
    are active - so this just reports the files present."""
    d = content_dir(content_type)
    exts = _cfg(content_type)["exts"]
    items = []
    for fname in sorted(os.listdir(d)):
        full = os.path.join(d, fname)
        if not os.path.isfile(full):
            continue
        if not fname.lower().endswith(exts):
            continue
        items.append({
            "filename": fname,
            "display_name": os.path.splitext(fname)[0],
            "size_kb": round(os.path.getsize(full) / 1024, 1),
        })
    return items


def delete_content(content_type: str, filename: str) -> None:
    """Removes one installed pack/shader. Guards against a filename that
    escapes the content folder (a caller passing '../something'), the same
    path-escape check delete_version uses, since this deletes a real file."""
    d = content_dir(content_type)
    target = os.path.join(d, filename)
    if os.path.dirname(os.path.abspath(target)) != os.path.abspath(d):
        raise ValueError("Refusing to delete a path outside the content folder.")
    if os.path.isfile(target):
        os.remove(target)


def install_local_content(content_type: str, src_path: str) -> str:
    """Copies a .zip the user already has on disk straight into the shared
    folder for this content type - the same place download_content() writes
    to. Returns the filename it was stored as, adding a short suffix rather
    than clobbering an existing pack with the same name."""
    exts = _cfg(content_type)["exts"]
    label = _cfg(content_type)["label"].lower()
    if not src_path.lower().endswith(exts):
        raise ValueError(f"That's not a {label} (.zip) file.")
    if not os.path.isfile(src_path):
        raise ValueError("Couldn't find that file.")

    d = content_dir(content_type)
    filename = os.path.basename(src_path)
    dest = os.path.join(d, filename)
    if os.path.exists(dest):
        base, ext = os.path.splitext(filename)
        filename = f"{base}_{uuid.uuid4().hex[:6]}{ext}"
        dest = os.path.join(d, filename)
    shutil.copyfile(src_path, dest)
    return filename


def open_content_folder(content_type: str) -> None:
    d = content_dir(content_type)
    if os.name == "nt":
        os.startfile(d)
    elif os.uname().sysname == "Darwin":
        import subprocess
        subprocess.Popen(["open", d])
    else:
        import subprocess
        subprocess.Popen(["xdg-open", d])


def is_installed(content_type: str, filename: str) -> bool:
    return os.path.isfile(os.path.join(content_dir(content_type), filename))


# ---------------------------------------------------------------------------
# Discovery/download via Modrinth's public API (same endpoints as mods.py,
# just a different project_type facet).
# ---------------------------------------------------------------------------

def search_content(content_type: str, query: str, mc_version: str | None = None,
                    categories: list[str] | None = None, limit: int = 100) -> list[dict]:
    """Searches Modrinth for packs/shaders of this type, optionally scoped to a
    Minecraft version and one or more categories. With no query text this is a
    most-downloaded-first browse (see modrinth_search_index). No loader facet:
    resource packs have no loader, and shaders are matched by version/category
    so the results aren't over-narrowed to one shader loader."""
    project_type = _cfg(content_type)["project_type"]
    facets = [[f"project_type:{project_type}"]]
    if mc_version:
        facets.append([f"versions:{mc_version}"])
    if categories:
        facets.append([f"categories:{c}" for c in categories])

    cache_key = {
        "type": content_type, "query": query, "mc_version": mc_version,
        "categories": categories or [], "limit": limit,
    }

    def _fetch() -> list[dict]:
        params = {
            "query": query, "limit": str(limit), "facets": json.dumps(facets),
            "index": modrinth_search_index(query),
        }
        data = net.get_json(f"{MODRINTH_API}/search", params=params,
                            headers=MODRINTH_HEADERS, timeout=15)

        results = []
        for hit in data.get("hits", []):
            results.append({
                "project_id": hit.get("project_id"),
                "slug": hit.get("slug"),
                "title": hit.get("title"),
                "description": hit.get("description"),
                "icon_url": hit.get("icon_url"),
                "downloads": hit.get("downloads", 0),
                "author": hit.get("author"),
            })
        return rank_search_hits(results, query)

    # Same tiers as search_mods: 6h fresh, stale-while-revalidate, offline fallback.
    return local_cache.cached_call("search_content", cache_key, _fetch, max_age=6 * 3600)


def get_recommended_content(content_type: str, mc_version: str | None = None,
                            category: str | None = None) -> list[dict]:
    """The default browse view before the user searches: the most-downloaded
    packs/shaders of this type for the current version (and category, if one's
    picked). Unlike mods.py's curated slug list, this is a plain popularity
    browse - for cosmetics 'most popular' is exactly what a browse should show,
    and it can never come back empty the way a hard-coded slug list can if a
    slug is renamed upstream."""
    return search_content(
        content_type, "", mc_version=mc_version,
        categories=[category] if category else None,
    )


def get_content_download(content_type: str, project_id_or_slug: str,
                         mc_version: str | None = None) -> dict | None:
    """Finds the best matching version file for a pack/shader, filtered by MC
    version when given. Returns {filename, url, size_kb, version_number} or
    None if no matching version exists. No loader filter - see search_content."""
    params = {}
    if mc_version:
        params["game_versions"] = json.dumps([mc_version])

    cache_key = {"type": content_type, "project": project_id_or_slug, "mc_version": mc_version}

    def _fetch():
        versions = net.get_json(
            f"{MODRINTH_API}/project/{project_id_or_slug}/version",
            params=params, headers=MODRINTH_HEADERS, timeout=15,
        )
        if not versions:
            return None

        latest = versions[0]
        files = latest.get("files", [])
        primary = next((f for f in files if f.get("primary")), files[0] if files else None)
        if not primary:
            return None

        return {
            "filename": primary.get("filename"),
            "url": primary.get("url"),
            "size_kb": round(primary.get("size", 0) / 1024, 1),
            "version_number": latest.get("version_number"),
            # Modrinth publishes sha512/sha1 per file; carrying them here lets
            # download_content reject a corrupted/truncated transfer outright.
            "hashes": primary.get("hashes") or {},
        }

    # Between click and download start - 24h fresh, then SWR, offline fallback.
    return local_cache.cached_call("content_download", cache_key, _fetch, max_age=86400)


def download_content(content_type: str, download_url: str, filename: str,
                     progress_cb=None, hashes: dict | None = None) -> str:
    """Streams a pack/shader file into the shared folder for this content type.

    Goes through cubeon.net like every other download: retry with backoff,
    HTTP Range resume after a dropped connection, a global concurrency cap,
    and an atomic .part -> final replace so a half-file is never mistaken for
    a complete pack. (This was the last install path still doing a bare
    single-attempt requests.get - exactly why a brief Wi-Fi hiccup showed up
    to the user as a hard "network error" instead of quietly retrying.)

    hashes: the Modrinth file's {"sha512"/"sha1": ...} when known; a mismatch
    is rejected rather than installing corrupt bytes. progress_cb(downloaded,
    total) is throttled inside net. Returns the final path. No profile/version
    keying is needed - packs and shaders live in one shared, version-agnostic
    folder the game reads directly."""
    d = content_dir(content_type)
    dest = os.path.join(d, filename)
    algo, expected = None, None
    for a in ("sha512", "sha1"):
        if (hashes or {}).get(a):
            algo, expected = a, hashes[a].lower()
            break
    expected_pair = (algo, expected) if algo and expected else None
    net.download_to(dest, download_url, headers=MODRINTH_HEADERS, timeout=60,
                    expected_hash=expected_pair, progress_cb=progress_cb)
    return dest
