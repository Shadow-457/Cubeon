"""Server Browse (Servers tab > Browse view) - the data layer + wiring.

The catalogue is curated, but every player count comes from free keyless
status APIs (minetools -> mcstatus.io -> mcsrvstat.us, measured live
2026-10-18). These tests run OFFLINE: network is faked at `net.get_json`,
the one funnel every endpoint call goes through (see the module-map harness
rule - faking `requests.get` does NOT intercept the pooled session).

Run: python3 tools/test_server_browse.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# --- sandbox: redirect HOME to a scratch dir before cubeon binds its paths at
# import time, so tests never read/write the developer's real game dir/store.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home
_sandbox_home.isolate()

from cubeon import server_browse as sb  # noqa: E402

_passed, _failed = 0, 0


def ok(condition, message):
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  ok  {message}")
    else:
        _failed += 1
        print(f"  FAIL  {message}")


def section(title):
    print(title)


# --------------------------------------------------------------------------
section("MOTD cleaning (section codes, newlines, nbsp)")
ok(sb.clean_motd("§aHi §lthere") == "Hi there", "strips § codes")
ok(sb.clean_motd("line one\nline two") == "line one line two",
   "flattens newlines")
ok(sb.clean_motd("\u00a0padding\u2007 x\u202f") == "padding x",
   "eats unicode padding spaces")
ok(sb.clean_motd(None) == "" and sb.clean_motd("") == "",
   "empty in, empty out")
ok(sb.clean_motd("§") == "§", "a trailing lone § survives (not a code)")

# --------------------------------------------------------------------------
section("Address parsing")
ok(sb.parse_address("mc.hypixel.net") == ("mc.hypixel.net", 25565),
   "bare host gets the default port")
ok(sb.parse_address("host.example:25566") == ("host.example", 25566),
   "host:port is honoured")
ok(sb.parse_address("  mc.hypixel.net  ") == ("mc.hypixel.net", 25565),
   "surrounding whitespace is trimmed")
ok(sb.parse_address("https://mc.hypixel.net:25565") == ("mc.hypixel.net", 25565),
   "a pasted URL is unwrapped")
ok(sb.parse_address("mc.hypixel.net/some/path") == ("mc.hypixel.net", 25565),
   "a trailing path is dropped")
for bad in ["", "   ", "a b", "host:abc", "host:", "host:99999", ":25565"]:
    try:
        sb.parse_address(bad)
        ok(False, f"rejects {bad!r}")
    except ValueError:
        ok(True, f"rejects {bad!r}")

# --------------------------------------------------------------------------
section("Catalogue integrity (the data users will see)")
names = [e["name"] for e in sb.CATALOGUE]
hosts = [e["host"] for e in sb.CATALOGUE]
ok(len(sb.CATALOGUE) >= 15, f"the catalogue is seeded ({len(sb.CATALOGUE)} servers)")
ok(len(set(hosts)) == len(hosts), "no duplicate hosts")
ok(all(h == h.lower().strip() for h in hosts), "hosts are lowercase")
ok(all(e.get("name") and e.get("host") and e.get("blurb") and
       isinstance(e.get("tags"), list) and e["tags"] for e in sb.CATALOGUE),
   "every entry carries name, host, tags and a blurb")
ok(all(t in sb.TAGS for e in sb.CATALOGUE for t in e["tags"]),
   "every used tag exists in the TAGS chip list")
ok(not any("cracked" in e["tags"] and "premium" in e["tags"]
           for e in sb.CATALOGUE),
   "no server is both cracked and premium")
ok("mc.hypixel.net" in hosts, "Hypixel is in (the anchor everyone looks for)")
ok(all(len(e["blurb"]) > 20 for e in sb.CATALOGUE),
   "blurbs actually say something")

# --------------------------------------------------------------------------
section("Search + tag filter")
prison = sb.search_servers("prison")
ok(any(e["name"] == "Purple Prison" for e in prison),
   "text search finds Purple Prison")
ok(all("prison" in " ".join([e["name"], e["host"], e["blurb"],
                             " ".join(e["tags"])]).lower()
        for e in prison), "hits really contain the query")
cracked = sb.search_servers(tag="cracked")
ok(cracked and all("cracked" in e["tags"] for e in cracked),
   f"tag filter works ({len(cracked)} cracked entries)")
ok(len(sb.search_servers("zzzznope")) == 0, "no hits for nonsense")
ok(sb.search_servers("MANACUBE") and
   all(e["name"] != "MANACUBE" for e in sb.search_servers("MANACUBE")),
   "search is case-insensitive on name")
ok(len(sb.search_servers()) == len(sb.CATALOGUE),
   "empty query returns the whole catalogue")
combo = sb.search_servers("skyblock", tag="cracked")
ok(all("cracked" in e["tags"] and "skyblock" in
       " ".join([e["name"], e["host"], e["blurb"], " ".join(e["tags"])]).lower()
       for e in combo), "query + tag combine with AND")

# --------------------------------------------------------------------------
section("Sort: most playing -> none playing -> unknown")


def _entry(status):
    e = {"name": "x", "host": f"h{abs(hash(str(status)))}", "tags": [],
         "blurb": "b"}
    if status is not None:
        e["status"] = status
    return e


on1 = _entry({"online": True, "players": 500})
on2 = _entry({"online": True, "players": 9000})
on3 = _entry({"online": True, "players": 0})
off = _entry({"online": False, "players": 0})
unk = _entry(None)
nostatus = {"name": "y", "host": "plain", "tags": [], "blurb": "b"}
got = sb.sort_by_status([on1, nostatus, unk, off, on3, on2])
order = [id(x) for x in got]
ok(order.index(id(on2)) < order.index(id(on1)) < order.index(id(on3)),
   "online sorted by players descending")
ok(order.index(id(on3)) < order.index(id(off)),
   "offline sorts below online")
ok(order.index(id(off)) < order.index(id(unk)) and
   order.index(id(off)) < order.index(id(nostatus)),
   "unknown entries never rank above real offline data (stable within ties)")
big_first = sb.sort_by_status([on1, on2])
ok(big_first[0]["status"]["players"] == 9000, "9000 beats 500")

# --------------------------------------------------------------------------
section("Endpoint parsers (faked net.get_json, real shapes)")
_real_get_json = sb.net.get_json


def _fake_json(responses):
    """Replace net.get_json with a canned responder keyed by url substring."""
    def fake(url, **kwargs):
        for needle, value in responses:
            if needle in url:
                if isinstance(value, Exception):
                    raise value
                return value
        raise AssertionError(f"unexpected url {url}")

    sb.net.get_json = fake
    return None


try:
    # minetools: players + version + description (its "error" key marks misses)
    _fake_json([("minetools", {
        "players": {"online": 42, "max": 100},
        "version": {"name": "Requires MC 1.8 / 1.21"},
        "description": "§aHi\n§lthere", "latency": 12})])
    s = sb._minetools("h", 25565)
    ok(s and s["online"] and s["players"] == 42 and s["max"] == 100,
       "minetools shape parses")
    ok(s["motd"] == "Hi there" and
       s["version"] == "Requires MC 1.8 / 1.21", "minetools motd/version")
    _fake_json([("minetools", {"error": "yeah:no"})])
    ok(sb._minetools("h", 25565) is None, "minetools error -> None (falls back)")
    _fake_json([("minetools", {"players": "garbage"})])
    ok(sb._minetools("h", 25565) is None, "minetools junk shape -> None")

    # mcstatus.io: online flag + motd.clean dict
    _fake_json([("mcstatus.io", {
        "online": True, "players": {"online": 7, "max": 20},
        "version": "1.21.4",
        "motd": {"raw": "§aHi", "clean": ["Hi", "there"]}})])
    s = sb._mcstatus("h", 25565)
    ok(s and s["players"] == 7 and s["motd"] == "Hi there" and
       s["version"] == "1.21.4", "mcstatus shape parses (motd.clean list)")

    # mcsrvstat.us: motd.clean as list of lines
    _fake_json([("mcsrvstat", {
        "online": True, "players": {"online": 3, "max": 10},
        "version": "Velocity 1.7.2-26.3", "motd": {"clean": ["A", "B"]}})])
    s = sb._mcsrvstat("h", 25565)
    ok(s and s["players"] == 3 and s["motd"] == "A B", "mcsrvstat shape parses")
finally:
    sb.net.get_json = _real_get_json

# --------------------------------------------------------------------------
section("Fallback chain + offline shape")
_real_fetch = sb._fetch_status
try:
    sb.net.get_json = lambda url, **k: (_ for _ in ()).throw(
        OSError("network down"))
    status = sb._fetch_status("host.example", 25565)
    ok(status == {"online": False, "players": 0, "max": 0, "version": "",
                  "motd": "", "latency": None},
       "all endpoints down -> the honest offline shape")
finally:
    sb.net.get_json = _real_get_json

try:
    calls = []

    def flaky(url, **kwargs):
        calls.append(url)
        if "minetools" in url:
            raise OSError("minetools is sad today")
        if "mcstatus.io" in url:
            return {"online": True, "players": {"online": 5, "max": 10},
                    "version": "1.21", "motd": {"clean": ["ok"]}}
        raise AssertionError("should not be reached")

    sb.net.get_json = flaky
    status = sb._fetch_status("host.example", 25565)
    ok(status["online"] and status["players"] == 5 and len(calls) == 2,
       "endpoint 1 failing falls through to endpoint 2")
finally:
    sb.net.get_json = _real_get_json

# --------------------------------------------------------------------------
section("Caching (memory TTL, disk TTL, stale flag, refresh)")
with tempfile.TemporaryDirectory() as tmp:
    sb._DISK_PATH = os.path.join(tmp, "status.json")
    sb._MEMORY.clear()
    fetches = {"n": 0}

    def counting(host, port):
        fetches["n"] += 1
        return {"online": True, "players": fetches["n"], "max": 100,
                "version": "1.21", "motd": "m", "latency": None}

    sb._fetch_status = counting
    try:
        a = sb.get_status("cache.example")
        b = sb.get_status("cache.example")
        ok(fetches["n"] == 1 and a["players"] == 1 and b["players"] == 1,
           "second call inside the TTL is served from memory")
        c = sb.get_status("cache.example", refresh=True)
        ok(fetches["n"] == 2 and c["players"] == 2,
           "refresh=True bypasses the memory cache")
        sb._MEMORY.clear()
        d = sb.get_status("cache.example")
        ok(d.get("stale") is True and d["players"] == 2 and
           fetches["n"] == 2,
           "a fresh disk entry serves last-known with the stale flag")
        # expire the disk entry -> a real refetch, and the disk file was used
        sb._MEMORY.clear()
        disk = json.load(open(sb._DISK_PATH))
        disk["cache.example:25565"]["t"] = 0
        json.dump(disk, open(sb._DISK_PATH, "w"))
        sb.get_status("cache.example")
        ok(fetches["n"] == 3, "an expired disk entry triggers a refetch")
    finally:
        sb._fetch_status = _real_fetch
        sb._MEMORY.clear()

# --------------------------------------------------------------------------
section("icon_url + browse() end to end (status faked)")
ok(sb.icon_url("mc.hypixel.net") ==
   "https://api.minetools.eu/favicon/mc.hypixel.net", "favicon URL shape")
ok(sb.icon_url("host.example:25566") ==
   "https://api.minetools.eu/favicon/host.example",
   "port is stripped from the favicon URL (it is per-host)")
ok(sb.icon_url("not a host") is None, "garbage in, None out")

with tempfile.TemporaryDirectory() as tmp:
    sb._DISK_PATH = os.path.join(tmp, "status.json")
    sb._MEMORY.clear()
    sb._fetch_status = lambda host, port: {
        "online": host != "emc.gs", "players": 123 if host != "emc.gs" else 0,
        "max": 200, "version": "1.21", "motd": "live", "latency": None}
    try:
        rows = sb.browse()
        ok(len(rows) == len(sb.CATALOGUE), "browse returns the full catalogue")
        ok(all("status" in e and "icon" in e for e in rows),
           "every row is annotated with status + icon")
        ok(rows[0]["status"]["players"] == 123 and rows[-1]["status"]["online"]
           is False, "online servers sort ahead of the offline one")
        ok(rows[0]["icon"].startswith("https://api.minetools.eu/favicon/"),
           "icons point at the cacheable favicon endpoint")
        hits = sb.browse(tag="cracked")
        ok(hits and all("cracked" in e["tags"] for e in hits),
           "browse(tag=...) filters like search does")

        # instant-paint mode: NEVER network - uncached entries stay statusless
        sb._MEMORY.clear()
        os.unlink(sb._DISK_PATH)
        fetches = {"n": 0}

        def counting(host, port):
            fetches["n"] += 1
            return {"online": True, "players": 1, "max": 2, "version": "v",
                    "motd": "m", "latency": None}

        sb._fetch_status = counting
        try:
            rows = sb.browse(statuses="cached")
            ok(fetches["n"] == 0,
               "statuses='cached' never touches the network")
            ok(all(e["status"] is None for e in rows),
               "uncached entries come back statusless (the UI paints them "
               "as 'checking…')")
            ok(len(rows) == len(sb.CATALOGUE),
               "cached mode still returns the full catalogue")
        finally:
            sb._fetch_status = _real_fetch
    finally:
        sb._fetch_status = _real_fetch
        sb._MEMORY.clear()

# --------------------------------------------------------------------------
section("UI wiring (imports + the views main.py glues together)")
try:
    import flet as ft  # noqa: F401
    from ui.server_browse_tab import build_server_browse_tab  # noqa: F401
    ok(True, "ui.server_browse_tab imports cleanly")
    main_src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "main.py"), encoding="utf-8").read()
    ok("build_server_browse_tab" in main_src and
       '"server_browse": server_browse_tab' in main_src,
       "main.py mounts the Browse view")
    ok('"server_browse"' in main_src and main_src.count("server_browse") >= 5,
       "chip + group keys + tabs + refresh wiring present")
except Exception as ex:  # a broken import is exactly what this must catch
    ok(False, f"UI wiring import failed: {ex}")

# --------------------------------------------------------------------------
print()
total = _passed + _failed
print(f"{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
