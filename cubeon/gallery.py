"""
Gallery - the LOCAL skins/capes library.

The Mojang "browse real players" system is GONE (remotes.py's real-player
fetch, the featured list, the prefetch): Browse is now a pair of ordinary
folders you drop files into, and "Get" installs a file through the exact same
pipeline a manual upload uses (cubeon/skins.py / cubeon/capes.py).

  ~/.cubeon_launcher/skin_library/   <- drop skin PNGs here (64x64 or 64x32)
  ~/.cubeon_launcher/cape_library/   <- drop cape images here (any shape)

Everything is local and network-free: the catalog lists the folders, the
previews are rendered from the actual pixels once and cached, and search is a
filter over the file names. Uploading your own PNG (Installed view) still works
exactly as before - the library is just a second intake for people who collect
skins as files.
"""
import json
import os

from PIL import Image

from .paths import CUBEON_HOME
from . import capes as _capes
from . import skins as _skins

GALLERY_DIR = os.path.join(CUBEON_HOME, "gallery")
PREVIEW_DIR = os.path.join(GALLERY_DIR, "previews")
# The drop-folders, next to everything else Cubeon stores under CUBEON_HOME.
SKIN_LIBRARY_DIR = os.path.join(CUBEON_HOME, "skin_library")
CAPE_LIBRARY_DIR = os.path.join(CUBEON_HOME, "cape_library")
INSTALLED_PATH = os.path.join(GALLERY_DIR, "installed.json")

_VALID_LIBRARY_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def ensure_gallery():
    """Make sure every directory the gallery touches exists. Network-free."""
    for d in (GALLERY_DIR, PREVIEW_DIR, SKIN_LIBRARY_DIR, CAPE_LIBRARY_DIR):
        os.makedirs(d, exist_ok=True)


def library_dir(kind: str) -> str:
    """The drop-folder for one kind ('skin' or 'cape')."""
    return SKIN_LIBRARY_DIR if kind == "skin" else CAPE_LIBRARY_DIR
# ---------------------------------------------------------------------------
# Previews - rendered once from the actual pixels, then reused
# ---------------------------------------------------------------------------

def _preview_path(pid: str, kind: str) -> str:
    # "_v2": previews are rendered at their exact display size; stale sizes
    # from older builds must not be reused.
    return os.path.join(PREVIEW_DIR, f"{pid}_{kind}_v2.png")


def _cape_back_panel(sheet: Image.Image, scale: int = 6) -> Image.Image:
    """Crop a cape's visible back panel (10x16 region at (1,1)) and upscale it
    with nearest-neighbour. HD capes are reduced to their logical grid first.
    scale=6 -> a crisp 60x96 tile."""
    n = max(1, sheet.width // 64)
    back = sheet.crop((1 * n, 1 * n, 11 * n, 17 * n))
    if n > 1:
        back = back.resize((10, 16), Image.NEAREST)
    return back.resize((10 * scale, 16 * scale), Image.NEAREST)


_PREVIEW_MEMO: dict = {}


def _ensure_previews(path: str, kind: str, gid: str) -> str:
    """Render (if missing) the display preview for one library file and return
    its path. Reads only local pixels - no network. On any failure the raw
    file itself is the preview (the grid scales it down; still honest)."""
    ensure_gallery()
    dst = _preview_path(gid, kind)
    try:
        stat = os.stat(path)
        signature = (path, stat.st_mtime_ns, stat.st_size)
    except OSError:
        return path
    if not os.path.isfile(dst) or _PREVIEW_MEMO.get(dst) != signature:
        try:
            if kind == "skin":
                _skins.render_local_skin_preview(gid, dst, scale=3,
                                                 src_path=path)
            else:
                with Image.open(path) as im:
                    _cape_back_panel(im.convert("RGBA")).save(dst)
        except Exception:
            return path
        _PREVIEW_MEMO[dst] = signature
    return dst

# ---------------------------------------------------------------------------
# Search: fuzzy enough that users don't need exact file names
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    """Lowercase + keep only [a-z0-9] - so 'Cool Skin v2', 'cool_skin-v2'
    and 'coolskinv2' all collapse to the same token."""
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


def _match_score(query: str, name: str, tags: list[str]) -> int:
    """0 = no match; higher = better. Exact, prefix, substring, subsequence
    (typo tolerant), then tag substring."""
    q = _norm(query)
    if not q:
        return 1
    n = _norm(name)
    if not n:
        return 0
    if q == n:
        return 100
    if n.startswith(q):
        return 85
    if q in n:
        return 70
    if len(q) >= 3:
        it = iter(n)
        if all(ch in it for ch in q):
            return 45
    for tag in tags:
        tn = _norm(tag)
        if q and (q == tn or q in tn or tn in q):
            return 35
    return 0


def _apply_query(items: list[dict], query: str | None, limit: int | None) -> list[dict]:
    """Filter + sort a catalog. No query -> name order (the folder is already
    the user's curation). With a query -> best match first."""
    q = (query or "").strip()
    if q:
        scored = []
        for it in items:
            score = _match_score(q, it["name"], it.get("tags", []))
            if score > 0:
                scored.append((score, it))
        scored.sort(key=lambda pair: (-pair[0], pair[1]["name"].lower()))
        out = [it for _, it in scored]
    else:
        out = sorted(items, key=lambda it: it["name"].lower())
    if limit is not None:
        out = out[:limit]
    return out

# ---------------------------------------------------------------------------
# Catalog - one item per file in the library folder (network-free)
# ---------------------------------------------------------------------------

def _library_files(kind: str) -> "list[tuple[str, float]]":
    """(stem, mtime) for every image in the kind's drop-folder, sorted by
    name. Non-image extensions and dotfiles are skipped."""
    d = library_dir(kind)
    try:
        names = os.listdir(d)
    except OSError:
        return []
    out = []
    for name in sorted(names):
        stem, ext = os.path.splitext(name)
        if not stem or name.startswith("_") or ext.lower() not in _VALID_LIBRARY_EXTENSIONS:
            continue
        path = os.path.join(d, name)
        try:
            stat = os.stat(path)
            out.append((name, (stat.st_mtime_ns, stat.st_size)))
        except OSError:
            continue
    return out

# The catalog only changes when a library file is added/changed/removed, so
# rebuild it only then. Without this the browse grid re-read the folder and
# re-rendered previews on every keystroke, which made search feel slow.
_CATALOG_MEMO: dict[str, tuple] = {}


def _catalog(kind: str) -> list[dict]:
    """One item per library file that could be the requested kind:
    [{id, name, tags, sheet_path, preview_path, cached}].

    'id' is the file NAME (unique within the folder) - it is what Get passes
    to the install flow. Network-free."""
    files = _library_files(kind)
    sig = tuple(files)
    hit = _CATALOG_MEMO.get(kind)
    if hit is not None and hit[0] == sig:
        return hit[1]
    items = []
    d = library_dir(kind)
    for name, _mtime in files:
        path = os.path.join(d, name)
        stem = os.path.splitext(name)[0]
        items.append({
            "id": name, "name": stem, "tags": ["local"],
            "sheet_path": path,
            "preview_path": _ensure_previews(path, kind, name),
            "cached": True,
        })
    _CATALOG_MEMO[kind] = (sig, items)
    return items


def all_gallery_items(kind: str) -> list[dict]:
    """Everything Browse shows for one kind, no query. Network-free."""
    return _catalog(kind)


def matches_query(item: dict, query: str | None) -> bool:
    """True when the item survives the (fuzzy) query. Empty query = all."""
    return _match_score(query or "", item.get("name", ""),
                        item.get("tags", [])) > 0


def list_gallery_skins(query: str | None = None, limit: int | None = None) -> list[dict]:
    return _apply_query(all_gallery_items("skin"), query, limit)


def list_gallery_capes(query: str | None = None, limit: int | None = None) -> list[dict]:
    return _apply_query(all_gallery_items("cape"), query, limit)

# ---------------------------------------------------------------------------
# Removed-with-the-Mojang-system stubs. The names stay exported (launcher_core
# re-exports them and the fuzz harness probes them); they are honest no-ops now.
# ---------------------------------------------------------------------------

def featured_count() -> int:
    return 0


def featured_cached_count() -> int:
    return 0


def prefetch_featured(limit: int | None = None, *, force: bool = False) -> list[str]:
    return []


def suggest_player(query: str | None = None) -> list[dict]:
    return []


def load_player(name: str, *, force: bool = False) -> dict:
    """Gone with the Mojang lookup. Returns an empty snapshot shape so any
    leftover caller gets a harmless 'no art' answer instead of a crash."""
    return {"id": name, "name": name, "model": "classic",
            "has_skin": False, "has_cape": False,
            "skin_preview": None, "cape_preview": None}

# ---------------------------------------------------------------------------
# Installed bookkeeping (unchanged shape)
# ---------------------------------------------------------------------------

def _load_installed() -> dict:
    try:
        with open(INSTALLED_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {"skin": data.get("skin") or {}, "cape": data.get("cape") or {}}
    except (OSError, ValueError):
        pass
    return {"skin": {}, "cape": {}}


def _save_installed(state: dict) -> None:
    ensure_gallery()
    from .atomicio import write_json
    write_json(INSTALLED_PATH, state)


def _mark(kind: str, gid: str, filename: str) -> None:
    state = _load_installed()
    state[kind][gid] = filename
    _save_installed(state)


def gallery_id_for_file(kind: str, filename: str) -> str | None:
    for gid, fn in _load_installed().get(kind, {}).items():
        if fn == filename:
            return gid
    return None


def forget_file(kind: str, filename: str) -> None:
    state = _load_installed()
    if filename in state.get(kind, {}).values():
        state[kind] = {gid: fn for gid, fn in state[kind].items() if fn != filename}
        _save_installed(state)

# ---------------------------------------------------------------------------
# Install flows - go through the SAME pipeline as a manual upload
# ---------------------------------------------------------------------------

def _library_file(gid: str, kind: str) -> str:
    """Resolve an item id back to its library file. 'gid' is the file name
    inside the drop-folder; a bare stem is accepted too, so an old bookmark
    (or a typo in a caller) still resolves when there's exactly one match."""
    path = os.path.join(library_dir(kind), gid)
    if os.path.isfile(path):
        return path
    stem_matches = [n for n, _ in _library_files(kind)
                    if os.path.splitext(n)[0] == gid]
    if len(stem_matches) == 1:
        return os.path.join(library_dir(kind), stem_matches[0])
    raise ValueError(f"'{gid}' is no longer in your {kind} library folder.")


def install_gallery_skin(cfg: dict, gid: str) -> dict:
    """Installs a skin from the library folder and wears it immediately.
    Returns the skins.py metadata entry."""
    path = _library_file(gid, "skin")
    name = os.path.splitext(os.path.basename(path))[0]
    entry = _skins.add_custom_skin(path, name)
    _skins.set_active_skin(cfg, entry["filename"])
    _mark("skin", gid, entry["filename"])
    return entry


def install_gallery_cape(cfg: dict, gid: str) -> dict:
    """Installs a cape from the library folder and wears it. Returns the
    capes.py metadata entry."""
    path = _library_file(gid, "cape")
    name = os.path.splitext(os.path.basename(path))[0]
    entry = _capes.add_custom_cape(path, name)
    _capes.set_active_cape(cfg, entry["filename"])
    _mark("cape", gid, entry["filename"])
    return entry
