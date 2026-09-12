"""
cubeon/remotes.py - real, free, 24/7 sources for Minecraft cosmetics.

Cubeon's gallery used to ship procedurally-drawn placeholder art. This module
replaces that with REAL content pulled from the same free public APIs the
vanilla game itself uses, so what you browse is real players' gear, not
invented pixels.

Sources (all keyless, free, reachable 24/7 - verified live at 2026-09-10):

  * Mojang session API - turn a username into a UUID:
        GET https://api.mojang.com/users/profiles/minecraft/<name>
  * Mojang session server - the real profiles blob (contains the skin PNG url,
    plus a cape when the account actually owns one):
        GET https://sessionserver.mojang.com/session/minecraft/profile/<uuid>
    then download the actual PNG from textures.minecraft.net (http -> https
    upgrade, because Mojang still serves bare http texture URLs).

EVERYTHING is cached under CUBEON_HOME/remotes/<id>/ with a 24h TTL, so the
public APIs are called sparingly, a re-browse is instant, and an offline start
still shows the last look seen for any player you've already looked at.

Design notes for testers: all HTTP goes through the module-level TEST_HANDLER
hook when set, so the suite can exercise resolve/fetch/parse paths with a fake
server and zero network. When TEST_HANDLER is None the real APIs are used.
"""
import base64
import json
import logging
import os
import time

from .lazy import LazyModule
requests = LazyModule("requests")

log = logging.getLogger(__name__)

from .paths import CUBEON_HOME  # noqa: E402

# Where real player looks are cached. Per-player subdir keyed by canonical
# (lowercased) username: profile.json + skin.png + cape.png.
REMOTE_DIR = os.path.join(CUBEON_HOME, "remotes")

# We never want to hammer Mojang's public API. 24h is plenty for a cosmetic
# lookup that is really "show me this player" - and we fall back to stale
# cache when offline, so a cold outage never blanks an already-seen player.
CACHE_TTL = 24 * 3600

# Tests point this at a fake server. Signature: f(url) -> bytes (raise on
# failure). Overriding it is the ONLY network escape hatch the suite needs.
TEST_HANDLER = None

_UA = ("Cubeon/1.0 (cosmetics gallery; "
       "https://github.com/Shadow-457/Cubeon)")

# Mojang endpoints. Hostnames kept as constants so tests can grep + monkeypatch
# them without touching every call site.
API_MOJANG = "https://api.mojang.com/users/profiles/minecraft"
SESSION_SERVER = "https://sessionserver.mojang.com/session/minecraft/profile"
TEXTURES_SERVER = "https://textures.minecraft.net/texture"


# ---------------------------------------------------------------------------
# Curated "Recommended" players
#
# The gallery can only show a player once their real art is cached, and on a
# fresh install the cache is empty - which is why Browse used to look broken.
# This is a hand-picked list of real, long-lived accounts that RESOLVE on
# Mojang and mostly OWN CAPES (verified live 2026-09-10). We ship NO artwork
# (that would be the players' - and Mojang's - to hand out); only the names.
# `prefetch_featured()` pulls their real skin/cape into the 24h cache so the
# Recommended grid fills itself, and `search` orders/filters by this list.
#
# Cape ownership drifts (players change capes/names), so the cape catalog
# still reflects what Mojang actually returns - the flag here is only for
# ordering and search tags, never a promise.
# ---------------------------------------------------------------------------
FEATURED_PLAYERS = [
    {"name": "jeb_",            "tags": ["recommended", "cape", "mojang"]},
    {"name": "Dinnerbone",      "tags": ["recommended", "cape", "mojang"]},
    {"name": "Grumm",           "tags": ["recommended", "cape", "mojang"]},
    {"name": "slicedlime",      "tags": ["recommended", "cape", "mojang"]},
    {"name": "Grian",           "tags": ["recommended", "cape", "slim"]},
    {"name": "impulseSV",       "tags": ["recommended", "cape"]},
    {"name": "fWhip",           "tags": ["recommended", "cape", "slim"]},
    {"name": "Hypixel",         "tags": ["recommended", "cape"]},
    {"name": "CaptainSparklez", "tags": ["recommended", "cape"]},
    {"name": "AntVenom",        "tags": ["recommended", "cape", "slim"]},
    {"name": "SethBling",       "tags": ["recommended", "cape"]},
    {"name": "Technoblade",     "tags": ["recommended", "cape"]},
    {"name": "SB737",           "tags": ["recommended", "cape", "slim"]},
    {"name": "GeminiTay",       "tags": ["recommended", "cape", "slim"]},
    {"name": "Notch",           "tags": ["recommended", "classic"]},
    {"name": "MumboJumbo",      "tags": ["recommended", "classic"]},
    {"name": "Docm77",          "tags": ["recommended", "classic"]},
    {"name": "Etho",            "tags": ["recommended", "classic"]},
    {"name": "Dream",           "tags": ["recommended", "slim"]},
    {"name": "VintageBeef",     "tags": ["recommended", "slim"]},
]

# Lowercased names known to own a cape (verified 2026-09-10) - used to build
# the recommended CAPE catalog before the cache has been filled. The item is
# still dropped if Mojang no longer returns a cape.
FEATURED_CAPE_NAMES = frozenset({
    "jeb_", "dinnerbone", "grumm", "slicedlime", "grian", "impulsesv",
    "fwhip", "hypixel", "captainsparklez", "antvenom", "sethbling",
    "technoblade", "sb737", "geminity",
})


def _http_get(url: str, timeout: int = 25) -> bytes:
    """Fetch bytes from a URL. TEST_HANDLER wins when set (tests); otherwise
    the real API over `requests`. Raises on any failure - callers translate
    that into honest user-facing status."""
    if TEST_HANDLER is not None:
        return TEST_HANDLER(url)
    resp = requests.get(url, headers={"User-Agent": _UA}, timeout=timeout)
    resp.raise_for_status()
    return resp.content


def _player_dir(pid: str) -> str:
    return os.path.join(REMOTE_DIR, pid)


def _profile_path(pid: str) -> str:
    return os.path.join(_player_dir(pid), "profile.json")


def _load_profile(pid: str) -> dict | None:
    try:
        with open(_profile_path(pid), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _fresh(profile: dict | None) -> bool:
    if not profile:
        return False
    return (time.time() - profile.get("fetched_at", 0)) < CACHE_TTL


def cached_player_ids() -> list[str]:
    """ids (canonical lowercased usernames) that have a cached profile.
    Network-free; used to populate the Browse grid for already-seen players
    and to decide which previews the gallery may show offline."""
    if not os.path.isdir(REMOTE_DIR):
        return []
    return sorted(
        d for d in os.listdir(REMOTE_DIR)
        if os.path.isfile(_profile_path(d))
        and os.path.isfile(os.path.join(_player_dir(d), "skin.png"))
    )


def featured_names() -> list[str]:
    """The curated recommended names, in display order. Network-free."""
    return [p["name"] for p in FEATURED_PLAYERS]


def featured_count() -> int:
    """How many names are in the curated recommended list. Network-free."""
    return len(FEATURED_PLAYERS)


def cached_display_names() -> list[str]:
    """Canonical (mixed-case) names of every player with a cached profile,
    fresh or stale. Network-free - reads the profile files only. Used for
    fuzzy suggestions WITHOUT accidentally refreshing a stale entry."""
    names = []
    for pid in cached_player_ids():
        prof = _load_profile(pid)
        if prof and prof.get("name"):
            names.append(prof["name"])
    return names


def featured_tags(name: str) -> list[str]:
    """Search tags for a featured name (empty for a non-featured one)."""
    low = (name or "").lower()
    for p in FEATURED_PLAYERS:
        if p["name"].lower() == low:
            return list(p["tags"])
    return []


def featured_cape_names() -> list[str]:
    """Featured names that (were verified to) own a cape. Network-free."""
    return [n for n in featured_names() if n.lower() in FEATURED_CAPE_NAMES]


def featured_cached_count() -> int:
    """How many featured players are already cached and fresh. Network-free -
    the UI uses this to decide whether a prefetch is worth starting."""
    n = 0
    for name in featured_names():
        prof = _load_profile(name.lower())
        if prof is not None and _fresh(prof):
            n += 1
    return n


def prefetch_featured(limit: int | None = None, *, force: bool = False) -> list[str]:
    """Fetch + cache the recommended players' real looks (network).

    Never raises: a name Mojang can't resolve or a dead network is skipped, so
    a partial prefetch still fills part of the grid. Fresh cached players are
    short-circuited by ensure_player, so calling this on every app start is
    cheap once the cache is warm. Returns the ids it resolved.

    Call this OFF the UI thread - it does real HTTP. `limit` caps how many to
    resolve in one pass (the UI starts with a small batch so tiles appear
    fast)."""
    resolved: list[str] = []
    for name in featured_names():
        if limit is not None and len(resolved) >= limit:
            break
        try:
            snap = ensure_player(name, force=force)
        except Exception as ex:  # noqa: BLE001 - prefetch is best-effort
            log.info("prefetch %s: %s", name, ex.__class__.__name__)
            continue
        if snap and snap.get("id"):
            resolved.append(snap["id"])
    return resolved


def resolve_ign(name: str) -> tuple[str, str] | None:
    """username -> (uuid, canonical_name). None when Mojang can't resolve it
    (unknown/offline account, network problem)."""
    name = (name or "").strip()
    if not name:
        return None
    try:
        body = _http_get(f"{API_MOJANG}/{name}")
    except Exception as ex:  # noqa: BLE001 - callers want a plain failure
        log.info("resolve %s: %s", name, ex.__class__.__name__)
        return None
    try:
        data = json.loads(body.decode("utf-8", "replace"))
        uuid_ = data["id"]
        canonical = data["name"]
    except (KeyError, ValueError) as ex:
        log.info("resolve %s: bad payload: %s", name, ex)
        return None
    return uuid_.lower(), canonical


def _decode_textures(uuid_: str) -> dict:
    """Hit the session server and return the parsed 'textures' dict from the
    base64 profile payload. Returns {} when there's nothing usable."""
    body = _http_get(f"{SESSION_SERVER}/{uuid_}")
    data = json.loads(body.decode("utf-8", "replace"))
    for prop in data.get("properties", []):
        if prop.get("name") != "textures":
            continue
        try:
            value = json.loads(base64.b64decode(prop["value"]))
        except (ValueError, TypeError):
            continue
        return value.get("textures", {})
    return {}


def _upgrade(url: str) -> str:
    # Mojang serves bare-http texture URLs; our client only does TLS.
    return url.replace("http://", "https://") if url.startswith("http://") else url


def _download(url: str) -> bytes | None:
    if not url:
        return None
    try:
        data = _http_get(_upgrade(url))
    except Exception as ex:  # noqa: BLE001 - best-effort texture
        log.info("download %s: %s", url, ex.__class__.__name__)
        return None
    return data


def ensure_player(pid_or_name: str, *, force: bool = False) -> dict | None:
    """Resolve + fetch + cache one real player. Returns a snapshot dict (or
    None if the name can't be resolved):

        {"id", "name", "uuid", "model",
         "skin_path", "cape_path"}   # each may be None

    skin/cape come from Mojang. When a fresh
    cached profile exists it short-circuits the network entirely; `force=True`
    re-fetches and refreshes the cache. On network failure mid-fetch we fall
    back to a stale cached copy if one exists, else surface None/partial.
    """
    # Already-cached and fresh -> no network at all.
    cached = _load_profile(pid_or_name)
    if not force and cached is not None and _fresh(cached):
        return _snapshot_from_profile(cached, pid_or_name)

    resolved = resolve_ign(pid_or_name)
    if resolved is None:
        # Offline but we have stale data? Prefer showing it over nothing.
        if cached is not None:
            return _snapshot_from_profile(cached, pid_or_name)
        return None

    uuid_, canonical = resolved
    pid = canonical.lower()

    # Textures (skin/cape) from Mojang.
    model = "classic"
    skin_bytes = cape_bytes = None
    try:
        textures = _decode_textures(uuid_)
        if "SKIN" in textures:
            skin_bytes = _download(textures["SKIN"].get("url"))
            if textures["SKIN"].get("metadata", {}).get("model") == "slim":
                model = "slim"
        if "CAPE" in textures:
            cape_bytes = _download(textures["CAPE"].get("url"))
    except Exception as ex:  # noqa: BLE001 - keep identity even if textures fail
        log.info("textures for %s: %s", pid, ex.__class__.__name__)

    d = _player_dir(pid)
    os.makedirs(d, exist_ok=True)
    skin_path = cape_path = None
    if skin_bytes:
        skin_path = os.path.join(d, "skin.png")
        with open(skin_path, "wb") as f:
            f.write(skin_bytes)
    if cape_bytes:
        cape_path = os.path.join(d, "cape.png")
        with open(cape_path, "wb") as f:
            f.write(cape_bytes)

    profile = {
        "id": pid, "name": canonical, "uuid": uuid_, "model": model,
        "has_skin": skin_path is not None, "has_cape": cape_path is not None,
        "fetched_at": int(time.time()),
    }
    try:
        with open(_profile_path(pid), "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2)
    except OSError as ex:
        log.warning("couldn't write remote profile for %s: %s", pid, ex)
    return {**profile, "skin_path": skin_path, "cape_path": cape_path}


def _snapshot_from_profile(profile: dict, _pid: str) -> dict:
    pid = profile.get("id") or _pid
    d = _player_dir(pid)
    skin_path = os.path.join(d, "skin.png") if profile.get("has_skin") else None
    cape_path = os.path.join(d, "cape.png") if profile.get("has_cape") else None
    return {
        "id": pid, "name": profile.get("name", pid), "uuid": profile.get("uuid"),
        "model": profile.get("model", "classic"),
        "skin_path": (skin_path if (skin_path and os.path.isfile(skin_path)) else None),
        "cape_path": (cape_path if (cape_path and os.path.isfile(cape_path)) else None),
    }