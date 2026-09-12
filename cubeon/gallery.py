"""
Gallery - browse REAL Minecraft players and wear their real gear.

Before this module, the gallery shipped procedurally-drawn placeholder skins
and capes. Now it fetches the real thing from the free, keyless, 24/7 APIs the
vanilla game itself uses (see cubeon/remotes.py): Mojang for the player's real
skin and cape. "Get" on a tile installs that player's actual skin/cape through
the exact same pipeline an upload uses (cubeon/skins.py / cubeon/capes.py).

This is deliberately REAL content, not invented pixels: the id for every tile
is a real Minecraft username, and the previews are the player's actual art.

Installed bookkeeping (installed.json: {skin:{gid:filename}, cape:{...}} ->
installed filename) and the install-flow shapes are unchanged from the earlier
generation-based design, so the Browse|Installed UI and its tests keep working.

Fetching is cached under CUBEON_HOME/remotes/ by remotes.py (24h TTL with
offline fallback); the list functions here are NETWORK-FREE - they only read
the cache, so the Profile dialog never hits the internet just to draw a grid.
"""
import json
import os

from PIL import Image

from .paths import CUBEON_HOME
from . import capes as _capes
from . import remotes as _remotes
from . import skins as _skins

# Public cache root for this module's preview renditions (the raw skins/capes
# themselves live under CUBEON_HOME/remotes/ - see cubeon/remotes.py). Kept at
# the same CUBEON_HOME/gallery root the old module used so existing dirs stay
# tidy.
GALLERY_DIR = os.path.join(CUBEON_HOME, "gallery")
PREVIEW_DIR = os.path.join(GALLERY_DIR, "previews")
# Raw player art lives under remotes.REMOTE_DIR (cubeon/remotes.py); this
# module only adds preview renditions + the installed.json bookkeeping below.
INSTALLED_PATH = os.path.join(GALLERY_DIR, "installed.json")


def ensure_gallery():
    """Make sure every directory the gallery touches exists. Does NOT hit the
    network (the list functions are network-free by design)."""
    os.makedirs(GALLERY_DIR, exist_ok=True)
    os.makedirs(PREVIEW_DIR, exist_ok=True)
# ---------------------------------------------------------------------------
# Previews - rendered once from the cached real data, then reused
# ---------------------------------------------------------------------------

def _preview_path(pid: str, kind: str) -> str:
    # "_v2": the tile previews are now rendered at their exact display size
    # (see _ensure_previews), so previews made by the older builds have the
    # wrong dimensions and must not be reused.
    return os.path.join(PREVIEW_DIR, f"{pid}_{kind}_v2.png")


def _cape_back_panel(sheet: Image.Image, scale: int = 6) -> Image.Image:
    """Crop a cape's visible back panel (10x16 region at (1,1)) and upscale it
    with nearest-neighbour, mirroring capes.render_cape_preview. HD capes are
    reduced to their logical grid first. scale=6 -> a crisp 60x96 tile."""
    n = max(1, sheet.width // 64)
    back = sheet.crop((1 * n, 1 * n, 11 * n, 17 * n))
    if n > 1:
        back = back.resize((10, 16), Image.NEAREST)
    return back.resize((10 * scale, 16 * scale), Image.NEAREST)


def _ensure_previews(snap: dict) -> dict:
    """Render (if missing) the skin/cape previews for a cached real
    player. Returns a preview-path-per-kind dict; pieces with no source stay
    absent. Only READS the cache (no network).

    The skin body is rendered at scale=3 -> exactly 48x96, and the cape back
    at scale=6 -> exactly 60x96 - the same sizes the grid draws them at, so
    the client never rescales pixel art (which is what made the previews look
    soft)."""
    ensure_gallery()
    out = {}
    sid = snap["id"]
    if snap.get("skin_path"):
        dst = _preview_path(sid, "skin")
        if not os.path.isfile(dst):
            try:
                _skins.render_local_skin_preview(
                    sid, dst, scale=3, src_path=snap["skin_path"])
            except Exception:
                dst = snap["skin_path"]  # fall back to the raw sheet
        out["skin"] = dst
    if snap.get("cape_path"):
        dst = _preview_path(sid, "cape")
        if not os.path.isfile(dst):
            try:
                with Image.open(snap["cape_path"]) as im:
                    _cape_back_panel(im.convert("RGBA")).save(dst)
            except Exception:
                dst = snap["cape_path"]
        out["cape"] = dst
    return out
# ---------------------------------------------------------------------------
# Catalog (network-free)
# ---------------------------------------------------------------------------

def _snap_for_catalog(pid: str) -> dict | None:
    try:
        return _remotes.ensure_player(pid)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Search: fuzzy enough that users don't need exact Minecraft names
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    """Lowercase + keep only [a-z0-9] - so 'Captain_Sparklez', 'captain
    sparklez' and 'CaptainSparklez' all collapse to the same token."""
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


def _match_score(query: str, name: str, tags: list[str]) -> int:
    """0 = no match; higher = better. Exact, prefix, substring, subsequence
    (typo/abbreviation tolerant: 'jeb' finds 'jeb_', 'dslime' finds
    'slicedlime'), then tag substring."""
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
    # Subsequence: every query char appears in order (handles dropped vowels
    # and skipped words). Only for queries long enough to be meaningful.
    if len(q) >= 3:
        it = iter(n)
        if all(ch in it for ch in q):
            return 45
    for tag in tags:
        tn = _norm(tag)
        if q and (q == tn or q in tn or tn in q):
            return 35
    return 0


def _featured_rank() -> dict:
    return {n.lower(): i for i, n in enumerate(_remotes.featured_names())}


def _apply_query(items: list[dict], query: str | None, limit: int | None) -> list[dict]:
    """Filter + sort a catalog. No query -> curated order (featured first),
    cached art only. With a query -> best match first."""
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
        # Recommended view: never a wall of blank placeholder tiles - only
        # show players whose real art is actually in the cache.
        items = [it for it in items if it.get("cached", True)]
        rank = _featured_rank()

        def sort_key(it):
            featured = bool(it.get("featured"))
            return (0 if featured else 1,
                    rank.get(it["id"], 999) if featured else 0,
                    it["name"].lower())
        out = sorted(items, key=sort_key)
    if limit is not None:
        out = out[:limit]
    return out


def _catalog(kind: str, query: str | None = None, *,
             include_uncached: bool | None = None) -> list[dict]:
    """One item per cached real player that has the requested art:
    [{id, name, tags, sheet_path, preview_path, featured, cached}].

    Network-free. When `include_uncached` (default: only when a `query` is
    present), uncached featured players are ALSO included as placeholder items
    (sheet_path=None) so a search always offers a suggestion even before the
    background prefetch has pulled that player into the cache."""
    if include_uncached is None:
        include_uncached = bool((query or "").strip())
    featured = {n.lower() for n in _remotes.featured_names()}
    items = []
    seen = set()
    for pid in _remotes.cached_player_ids():
        snap = _snap_for_catalog(pid)
        if not snap:
            continue
        path = snap.get(f"{kind}_path")
        if not path:
            continue
        previews = _ensure_previews(snap)
        tags = ["real"]
        if snap.get("model"):
            tags.append(snap["model"])
        tags.extend(_remotes.featured_tags(snap["name"]))
        seen.add(pid.lower())
        items.append({
            "id": pid, "name": snap["name"], "tags": tags,
            "sheet_path": path,
            "preview_path": previews.get(kind, path),
            "featured": pid in featured,
            "cached": True,
        })
    if include_uncached:
        cape_only = kind == "cape"
        allowed = set(_remotes.featured_cape_names()) if cape_only else None
        for name in _remotes.featured_names():
            if name.lower() in seen:
                continue
            if allowed is not None and name not in allowed:
                continue
            items.append({
                "id": name, "name": name,
                "tags": _remotes.featured_tags(name),
                "sheet_path": None, "preview_path": None,
                "featured": True, "cached": False,
            })
    return items


# The catalog only changes when the remotes cache gains/loses a player (the
# prefetch runs in the background), so rebuild it only then. Without this the
# browse grid re-read every profile + re-rendered previews on every keystroke,
# which is what made search feel slow.
_CATALOG_MEMO: dict[str, tuple] = {}


def _cached_catalog(kind: str) -> list[dict]:
    sig = tuple(_remotes.cached_player_ids())
    hit = _CATALOG_MEMO.get(kind)
    if hit is not None and hit[0] == sig:
        return hit[1]
    items = _catalog(kind, include_uncached=True)
    _CATALOG_MEMO[kind] = (sig, items)
    return items


def all_gallery_items(kind: str) -> list[dict]:
    """The universal tile set for one browse grid: every cached player plus
    every not-yet-cached recommended player (placeholder art). Network-free and
    memoized. The UI builds one tile per item ONCE and filters a search by
    flipping `.visible` - no tree rebuild, so no image reload/flicker."""
    return [dict(it) for it in _cached_catalog(kind)]


def matches_query(item: dict, query: str | None) -> bool:
    """Whether a catalog item should be visible for `query`. Empty query shows
    the cached Recommended set; a query uses the same fuzzy matcher as search.
    Pure/network-free - safe to call per keystroke."""
    q = (query or "").strip()
    if not q:
        return bool(item.get("cached", True))
    return _match_score(q, item["name"], item.get("tags", [])) > 0


def list_gallery_skins(query: str | None = None, limit: int | None = None) -> list[dict]:
    """Real players' real skins as gallery tiles. Network-free. `query` filters
    with fuzzy matching (and may surface not-yet-cached recommended players);
    `limit` caps the result count."""
    return _apply_query(_cached_catalog("skin"), query, limit)


def list_gallery_capes(query: str | None = None, limit: int | None = None) -> list[dict]:
    """Real players' real capes (only accounts that own one). Network-free;
    same query/limit behaviour as list_gallery_skins."""
    return _apply_query(_cached_catalog("cape"), query, limit)


def featured_cached_count() -> int:
    """How many recommended players are already cached (network-free)."""
    return _remotes.featured_cached_count()


def featured_count() -> int:
    """Size of the curated recommended list (network-free)."""
    return _remotes.featured_count()


def prefetch_featured(limit: int | None = None, *, force: bool = False) -> list[str]:
    """Fetch the recommended players' real looks into the cache (network).
    Never raises; call OFF the UI thread. Returns the resolved ids."""
    return _remotes.prefetch_featured(limit=limit, force=force)


def suggest_player(name: str) -> str | None:
    """The closest cached/featured player name to `name`, or None.

    The free Mojang API only resolves EXACT names, so a typo means "not
    found". This is the wrapper that turns that dead end into "did you mean
    ...?": it fuzzy-matches against the curated list plus everything already
    cached. Network-free."""
    q = (name or "").strip()
    if not q:
        return None
    candidates = list(_remotes.featured_names())
    candidates.extend(_remotes.cached_display_names())
    best = None
    best_score = 0
    for cand in candidates:
        if _norm(cand) == _norm(q):
            return cand  # exact (ignoring punctuation/case) - no "did you mean"
        score = _match_score(q, cand, [])
        if score > best_score:
            best, best_score = cand, score
    return best if best_score >= 45 else None


# ---------------------------------------------------------------------------
# Public load (network - the one place the gallery touches the internet)
# ---------------------------------------------------------------------------
def load_player(name: str, *, force: bool = False) -> dict:
    """Fetch + cache a real player (via cubeon/remotes.py) and return a dict:
    {id, name, model, has_skin, has_cape, skin_preview, cape_preview}. Raises
    ValueError (honest, human message) when the name can't be resolved or the
    network is unavailable."""
    if not (name or "").strip():
        raise ValueError("Enter a Minecraft username first.")
    snap = _remotes.ensure_player(name, force=force)
    if snap is None:
        raise ValueError(
            f"Couldn't find '{name}' - double-check the spelling (it must be a "
            "real Mojang account) and that you're online.")
    previews = _ensure_previews(snap)
    return {
        "id": snap["id"], "name": snap["name"], "model": snap.get("model", "classic"),
        "has_skin": bool(snap.get("skin_path")),
        "has_cape": bool(snap.get("cape_path")),
        "skin_preview": previews.get("skin"),
        "cape_preview": previews.get("cape"),
    }


# ---------------------------------------------------------------------------
# Installed bookkeeping (unchanged shape from the old design)
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
    with open(INSTALLED_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


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

def _finalize_gallery(pid: str) -> dict:
    snap = _remotes.ensure_player(pid)
    if snap is None:
        raise ValueError(f"Player '{pid}' isn't cached - load them first.")
    return snap


def install_gallery_skin(cfg: dict, gid: str) -> dict:
    """Installs a real player's real skin and wears it immediately. Returns
    the skins.py metadata entry. 'gid' is the player's canonical username."""
    snap = _finalize_gallery(gid)
    if not snap.get("skin_path"):
        raise ValueError(f"{snap['name']} has no own skin to install.")
    entry = _skins.add_custom_skin(snap["skin_path"], snap["name"])
    _skins.set_active_skin(cfg, entry["filename"])
    _mark("skin", gid, entry["filename"])
    return entry


def install_gallery_cape(cfg: dict, gid: str) -> dict:
    """Installs a real player's real cape (if they own one) and wears it.
    Returns the capes.py metadata entry. Raises ValueError when the account
    has no cape - better honest than silently wearing the wrong thing."""
    snap = _finalize_gallery(gid)
    if not snap.get("cape_path"):
        raise ValueError(f"{snap['name']} doesn't have a cape to install.")
    entry = _capes.add_custom_cape(snap["cape_path"], snap["name"])
    _capes.set_active_cape(cfg, entry["filename"])
    _mark("cape", gid, entry["filename"])
    return entry
