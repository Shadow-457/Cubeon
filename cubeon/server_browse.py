"""Public-server browse - the data layer behind the Servers tab's Browse view.

What this is: a CURATED catalogue of well-known public Minecraft servers
(name, address, tags, a one-line "what it does" blurb) whose player counts
and online/offline state are always fetched LIVE from free, keyless status
APIs. Sort "most playing to none playing" is therefore honest: a famous
server that died sinks to the bottom of the list on its own.

Why curated + live, and not a full list: there is NO free, keyless API that
LISTS public servers (2026-10-18, measured: the list sites answer Cloudflare
403 to non-browser clients, the one open dataset repo on GitHub is gone).
Every "browse all servers" attempt that pretends otherwise silently breaks.
The tag chips and blurbs are editorial (written here, in the catalogue), and
"cracked" vs "premium" is likewise declared per entry - the free status
endpoints used to expose a cracked flag but no longer do, and pinging a
server cannot tell you its login policy. Anything not in the catalogue can
still be checked and joined by typing its address (see lookup()).

Status endpoints, in fallback order (all verified live 2026-10-18):
  1. api.minetools.eu/ping/<host>/<port>   - players + version + MOTD + icon
  2. api.mcstatus.io/v2/status/java/<h:p>  - players + version + clean MOTD
  3. api.mcsrvstat.us/3/<host[:port]>      - players + version + MOTD

Rate-limit friendliness: every host's status is cached in memory for
STATUS_TTL seconds, and last-known values are persisted to a small disk
file so a second launcher start inside the TTL (or a flaky network moment)
renders instantly from the previous good answer instead of hammering the
endpoints again.
"""
import json
import os
import re
import threading
import time
from urllib.parse import urlparse

from .lazy import LazyModule
requests = LazyModule("requests")

from . import net
from .paths import CUBEON_HOME, user_agent

# --------------------------------------------------------------------------
# The curated catalogue. Hosts were probed live on 2026-10-18 (every entry
# answered with a real MOTD; servers that block datacenter pings - TheArchon,
# DatBlock, VeltPvP - would show a FALSE "offline" here and are deliberately
# excluded; users reach them through the address lookup box instead).
# Tags are lowercase, single words; the UI derives its filter chips from this
# list, so adding a new tag here automatically adds the chip.
# --------------------------------------------------------------------------
CATALOGUE = [
    {"name": "Hypixel", "host": "mc.hypixel.net",
     "tags": ["minigames", "premium"],
     "blurb": "The biggest Minecraft server: Bed Wars, SkyBlock, Murder "
              "Mystery and dozens more minigames. Premium (account) only."},
    {"name": "Minehut", "host": "minehut.com",
     "tags": ["hosting", "cracked"],
     "blurb": "Free server hosting network - spin up your own server in "
              "minutes or hop into community servers. Cracked-friendly."},
    {"name": "Minemen Club", "host": "minemen.club",
     "tags": ["pvp", "practice", "cracked"],
     "blurb": "Practice PvP (Crystal/Nodebuff/Sumo) for 1.8-1.21 duelists. "
              "The EU practice staple. Cracked-friendly."},
    {"name": "PikaNetwork", "host": "play.pika-network.net",
     "tags": ["pvp", "minigames", "cracked"],
     "blurb": "Big cracked network: Bed Wars, Sky Wars, KitPvP, practice "
              "duels and lobbies full of events. Cracked-friendly."},
    {"name": "JartexNetwork", "host": "play.jartexnetwork.com",
     "tags": ["pvp", "minigames", "cracked"],
     "blurb": "Cracked all-rounder: SkyBlock, Prison, Bed Wars, KitPvP and "
              "custom events. Cracked-friendly."},
    {"name": "CubeCraft", "host": "play.cubecraft.net",
     "tags": ["minigames", "premium"],
     "blurb": "Polished minigames (Egg Wars, Sky Wars, Lucky Islands) with "
              "anti-cheat that actually works. Java + Bedrock. Premium only."},
    {"name": "ManaCube", "host": "mc.manacube.com",
     "tags": ["survival", "skyblock", "premium"],
     "blurb": "Custom SkyBlock, Survival, dungeons and islands with seasons "
              "and a daily calendar. Premium only."},
    {"name": "AkumaMC", "host": "play.akumamc.net",
     "tags": ["skyblock", "pvp", "cracked"],
     "blurb": "SkyBlock-focused network with seasonal resets, island "
              "upgrades and PvP arenas. Cracked-friendly."},
    {"name": "Purple Prison", "host": "purpleprison.net",
     "tags": ["prison", "cracked"],
     "blurb": "The classic prison server: mine, rank up, run contraband - "
              "running since 2014. Cracked-friendly."},
    {"name": "OPBlocks", "host": "opblocks.com",
     "tags": ["prison", "skyblock", "cracked"],
     "blurb": "SkyBlock, Prison and Survival with custom enchants and "
              "frequent events. Cracked-friendly."},
    {"name": "BlocksMC", "host": "blocksmc.com",
     "tags": ["minigames", "cracked"],
     "blurb": "Cracked minigames network: Bed Wars, Sky Wars, Cricket and "
              "arcade games. Cracked-friendly."},
    {"name": "2b2t", "host": "2b2t.org",
     "tags": ["anarchy", "survival", "premium"],
     "blurb": "The oldest anarchy server: no rules, no resets, a decade of "
              "ruins and a legendary queue. Premium only."},
    {"name": "Wynncraft", "host": "play.wynncraft.com",
     "tags": ["mmo", "rpg", "premium"],
     "blurb": "A full MMORPG inside Minecraft: quests, classes, dungeons "
              "and provinces. Premium only."},
    {"name": "EarthMC", "host": "play.earthmc.net",
     "tags": ["survival", "towny", "premium"],
     "blurb": "A 1:1000 scale Earth map with nations, towns and wars. "
              "Premium only."},
    {"name": "Grand Theft Minecart", "host": "play.gtm.network",
     "tags": ["minigames", "pvp", "premium"],
     "blurb": "GTA-style heists, cars and shootouts rebuilt in Minecraft. "
              "Premium only."},
    {"name": "EcoCityCraft", "host": "play.ecocitycraft.com",
     "tags": ["economy", "survival", "premium"],
     "blurb": "Long-running economy/towny server (since 2011) with a huge "
              "player market. Premium only."},
    {"name": "Empire Minecraft", "host": "emc.gs",
     "tags": ["survival", "economy", "premium"],
     "blurb": "Grief-free survival empire building with a mature community "
              "and player shops. Premium only."},
    {"name": "Performium", "host": "performium.net",
     "tags": ["survival", "minigames", "premium"],
     "blurb": "Survival, SkyBlock, creative plots and among-us-style "
              "minigames on one network. Premium only."},
]

# Every tag used above, in a stable display order (the UI's filter chips).
TAGS = ["minigames", "pvp", "skyblock", "survival", "prison", "anarchy",
        "mmo", "rpg", "towny", "economy", "hosting", "practice",
        "cracked", "premium"]

# --------------------------------------------------------------------------
# Status fetching
# --------------------------------------------------------------------------
STATUS_TTL = 120          # seconds a status answer stays fresh in memory
DISK_TTL = 900            # seconds the disk cache is trusted (15 min)
_TIMEOUT = 8              # per-endpoint timeout; keep the browse snappy

_MINETOOLS = "https://api.minetools.eu/ping/{host}/{port}"
_MCSTATUS = "https://api.mcstatus.io/v2/status/java/{host}:{port}"
_MCSRVSTAT = "https://api.mcsrvstat.us/3/{host}:{port}"

_MEMORY: dict = {}        # "host:port" -> (timestamp, status dict)
_MEM_LOCK = threading.Lock()
_DISK_PATH = os.path.join(CUBEON_HOME, "cache", "server_status.json")
_DISK_LOCK = threading.Lock()

# A §-format code is § + one char (color or formatting). MOTDs also embed
# newlines and the odd unicode nbsp - clean all of it into one plain line.
_SECTION = re.compile(r"§.")
_WS = re.compile(r"[\s\u00a0\u2007\u202f]+")


def clean_motd(raw: str | None) -> str:
    """MOTD (possibly with § codes and newlines) -> one plain line."""
    if not raw:
        return ""
    text = _SECTION.sub("", raw)
    return _WS.sub(" ", text).strip()


def parse_address(address: str, default_port: int = 25565) -> "tuple[str, int]":
    """'host' | 'host:port' | 'https://host:port' -> (host, port).

    Raises ValueError with a user-presentable message on nonsense (spaces,
    empty host, non-numeric port) - the caller shows it, we never guess."""
    text = (address or "").strip()
    if "://" in text:
        text = urlparse(text).netloc or ""
    text = text.split("/")[0].strip()
    if not text or " " in text:
        raise ValueError("Type a server address like mc.hypixel.net or "
                         "mc.hypixel.net:25565.")
    host, sep, port = text.partition(":")
    if not host:
        raise ValueError("That address has no hostname in it.")
    if not sep:
        return host, default_port
    if not port.isdigit() or not (0 < int(port) < 65536):
        raise ValueError(f"'{port}' is not a valid port number.")
    return host, int(port)


def _disk_load() -> dict:
    try:
        with open(_DISK_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _disk_store(entries: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_DISK_PATH), exist_ok=True)
        tmp = _DISK_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(entries, f)
        os.replace(tmp, _DISK_PATH)
    except Exception:
        # The disk cache is a convenience - losing it must never surface.
        pass


def _fresh(entry: dict, ttl: int) -> bool:
    return isinstance(entry, dict) and (time.time() - entry.get("t", 0)) < ttl


def _minetools(host: str, port: int) -> dict | None:
    try:
        resp = net.get_json(_MINETOOLS.format(host=host, port=port),
                            timeout=_TIMEOUT, attempts=1,
                            headers={"User-Agent": user_agent("serverbrowse")})
    except Exception:
        return None
    if not isinstance(resp, dict) or resp.get("error"):
        return None
    players = resp.get("players") or {}
    if not isinstance(players, dict) or "online" not in players:
        return None
    return {
        "online": True,
        "players": int(players.get("online") or 0),
        "max": int(players.get("max") or 0),
        "version": clean_motd(str((resp.get("version") or {}).get("name") or "")),
        "motd": clean_motd(resp.get("description")),
        "latency": resp.get("latency"),
    }


def _as_text(value) -> str:
    """Endpoint MOTD/version fields: usually str, sometimes a list of lines
    (mcstatus.io motd.clean, mcsrvstat motd.clean). One normalizer."""
    if isinstance(value, list):
        value = " ".join(str(x) for x in value)
    return str(value or "")


def _mcstatus(host: str, port: int) -> dict | None:
    try:
        resp = net.get_json(_MCSTATUS.format(host=host, port=port),
                            timeout=_TIMEOUT, attempts=1,
                            headers={"User-Agent": user_agent("serverbrowse")})
    except Exception:
        return None
    if not isinstance(resp, dict) or resp.get("online") is not True:
        return None
    players = resp.get("players") or {}
    motd = resp.get("motd") or {}
    clean = motd.get("clean") if isinstance(motd, dict) else motd
    return {
        "online": True,
        "players": int(players.get("online") or 0),
        "max": int(players.get("max") or 0),
        "version": clean_motd(str(resp.get("version") or "")),
        "motd": clean_motd(_as_text(clean)),
        "latency": None,
    }


def _mcsrvstat(host: str, port: int) -> dict | None:
    try:
        resp = net.get_json(_MCSRVSTAT.format(host=host, port=port),
                            timeout=_TIMEOUT, attempts=1,
                            headers={"User-Agent": user_agent("serverbrowse")})
    except Exception:
        return None
    if not isinstance(resp, dict) or resp.get("online") is not True:
        return None
    players = resp.get("players") or {}
    motd = resp.get("motd") or {}
    clean = motd.get("clean") if isinstance(motd, dict) else motd
    if isinstance(clean, list):
        clean = " ".join(str(x) for x in clean)
    return {
        "online": True,
        "players": int(players.get("online") or 0),
        "max": int(players.get("max") or 0),
        "version": clean_motd(str(resp.get("version") or "")),
        "motd": clean_motd(str(clean or "")),
        "latency": None,
    }


_FETCHERS = (_minetools, _mcstatus, _mcsrvstat)


def _fetch_status(host: str, port: int) -> dict:
    """Live status with the three-endpoint fallback, plus one shared shape
    for offline/unreachable (every endpoint answered, or none did)."""
    for fetch in _FETCHERS:
        status = fetch(host, port)
        if status is not None:
            return status
    return {"online": False, "players": 0, "max": 0, "version": "",
            "motd": "", "latency": None}


def get_status(address: str, *, refresh: bool = False) -> dict:
    """Live status for one address, cached (memory -> disk -> network).

    The returned dict always carries the full shape (online, players, max,
    version, motd) plus, when the answer came from disk rather than the
    network, stale: True - the UI shows 'last seen' instead of lying."""
    host, port = parse_address(address)
    key = f"{host}:{port}".lower()
    now = time.time()
    with _MEM_LOCK:
        hit = _MEMORY.get(key)
        if hit and not refresh and _fresh(hit, STATUS_TTL):
            return dict(hit["s"])
    disk = _disk_load()
    entry = disk.get(key)
    if entry and not refresh and _fresh(entry, DISK_TTL):
        with _MEM_LOCK:
            _MEMORY[key] = entry
        return {**entry["s"], "stale": True}
    status = _fetch_status(host, port)
    packed = {"t": now, "s": status}
    with _MEM_LOCK:
        _MEMORY[key] = packed
    with _DISK_LOCK:
        disk[key] = packed
        _disk_store(disk)
    return dict(status)


def icon_url(host: str) -> str | None:
    """A cacheable HTTP icon URL for the host (minetools /favicon/ endpoint).

    Deliberately NOT the ping's data-URI favicon: this URL feeds the shared
    icons disk cache, so art costs one request EVER per server, not one per
    render, and it keeps working across launcher restarts."""
    try:
        host, _port = parse_address(host)
    except ValueError:
        return None
    return f"https://api.minetools.eu/favicon/{host}"


# --------------------------------------------------------------------------
# Catalogue operations
# --------------------------------------------------------------------------

def _entry_host(entry: dict) -> str:
    return (entry.get("host") or "").strip().lower()


def list_servers() -> list:
    """The catalogue, each entry shallow-copied (callers may annotate)."""
    return [dict(e) for e in CATALOGUE]


def search_servers(query: str = "", tag: str | None = None) -> list:
    """Catalogue entries matching a case-insensitive name/tag/blurb query
    and an optional exact tag. Order is unspecified - status sorting is
    sort_by_status()'s job (kept separate so it can be applied or not)."""
    text = (query or "").strip().lower()
    out = []
    for entry in list_servers():
        if tag and tag not in (entry.get("tags") or []):
            continue
        if text:
            haystack = " ".join([entry.get("name", ""), entry.get("host", ""),
                                 entry.get("blurb", ""),
                                 " ".join(entry.get("tags") or [])]).lower()
            if text not in haystack:
                continue
        out.append(entry)
    return out


def sort_by_status(entries: list) -> list:
    """Most playing -> none playing, using whatever status annotation each
    entry carries (key 'status'; entries WITHOUT one sort as unknown).
    Online servers come first by player count descending, then offline
    ones (0 players but the server answered), then unknown/uncached."""
    def rank(entry: dict) -> "tuple[int, int]":
        status = entry.get("status")
        if status and status.get("online"):
            return (0, -int(status.get("players") or 0))
        if status is not None:      # an answer that said "not online"
            return (1, 0)
        return (2, 0)               # not checked yet / no cache

    return sorted(entries, key=rank)


def browse(query: str = "", tag: str | None = None,
           statuses: str = "fetch") -> list:
    """One call for the UI: search + status + sort. Each entry gains
    'status' (live or last-known shape, or None) and 'icon' (cacheable
    URL).

    statuses="fetch" (default): resolve every entry's status now, blocking
    until each is answered - the semantics of the original one-shot call.
    statuses="cached": NEVER touch the network; use memory/disk cache, and
    leave 'status' None where nothing is cached. The tab uses this for its
    INSTANT first paint (rows appear with "checking…" placeholders) and
    then fills live numbers in progressively - a first visit must not sit
    on an empty list for the length of 18 status fetches."""
    entries = search_servers(query, tag)
    results = []
    disk = _disk_load()
    with _MEM_LOCK:
        mem_snapshot = {k: v["s"] for k, v in _MEMORY.items()}
    for entry in entries:
        key = _entry_host(entry)
        status = None
        if key in mem_snapshot:
            status = mem_snapshot[key]
        elif key in disk and _fresh(disk[key], DISK_TTL):
            status = {**disk[key]["s"], "stale": True}
        if status is None and statuses == "fetch":
            # Network happens OUTSIDE the caller's thread contract: browse()
            # itself is always called from a background worker (the tab only
            # paints rows), so a blocking fetch here is fine and gives first
            # paint real numbers instead of a two-stage flicker.
            status = get_status(key)
        item = dict(entry)
        item["status"] = status
        item["icon"] = icon_url(key)
        results.append(item)
    return sort_by_status(results)
