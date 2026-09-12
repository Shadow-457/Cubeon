#!/usr/bin/env python3
"""
Tests for the REAL-player cosmetics gallery (cubeon/remotes.py + gallery.py).

Run with:
    python tools/test_gallery.py

No real network, no real .minecraft: HOME is pointed at a temp dir and all
HTTP goes through remotes.TEST_HANDLER (the testable hook), serving a fake
Mojang session + textures server for one fake player.

Covers: fetching real content into the cache (resolve -> session -> texture,
http->https upgrade, cape absence), that the catalog list
functions are NETWORK-FREE and reflect the cache, caching (fresh short-
circuit, stale offline fallback), the install flows landing in skins.py /
capes.py state and wearing immediately, installed bookkeeping round-trips,
and honest failures (unknown player, capless account). Exit code 0 iff every
check passes.
"""
import base64
import io
import json
import os
import sys
import types

import _sandbox_home
_home = _sandbox_home.isolate()

_fake_mc = os.path.join(_home, ".minecraft")
_mll = types.ModuleType("minecraft_launcher_lib")
_mll.utils = types.SimpleNamespace(get_minecraft_directory=lambda: _fake_mc)
sys.modules["minecraft_launcher_lib"] = _mll

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image                                     # noqa: E402

from cubeon import gallery, capes, skins, remotes  # noqa: E402

_checks = []


def check(name, ok, detail=""):
    _checks.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


def _png(size, color):
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, "PNG")
    return buf.getvalue()


SKIN_BYTES = _png((64, 64), (21, 119, 199, 255))
CAPE_BYTES = _png((64, 32), (230, 60, 40, 255))

U = "11111111111111111111111111111111"
_hits = {"n": 0}


def _tex_payload(cape=True):
    textures = {"SKIN": {"url": "http://textures.minecraft.net/texture/aaaa"}}
    if cape:
        textures["CAPE"] = {"url": "http://textures.minecraft.net/texture/bbbb"}
    val = base64.b64encode(json.dumps({"textures": textures}).encode()).decode()
    return json.dumps({
        "id": U, "name": "RealPlayer",
        "properties": [{"name": "textures", "value": val}],
    }).encode()


def _handler(url, cape=True):
    _hits["n"] += 1
    if "users/profiles/minecraft" in url:
        return json.dumps({"id": U, "name": "RealPlayer"}).encode()
    if "/session/minecraft/profile" in url:
        return _tex_payload(cape=cape)
    if "textures.minecraft.net/texture/aaaa" in url:
        return SKIN_BYTES
    if "textures.minecraft.net/texture/bbbb" in url:
        return CAPE_BYTES
    raise RuntimeError("fake server hit an unexpected url: " + url)


# 1. Fetch into the cache (real content, not generated)
# ------------------------------------------------------
remotes.TEST_HANDLER = lambda url: _handler(url, cape=True)
gallery.ensure_gallery()

check("gallery lists are empty before any fetch", not gallery.list_gallery_skins())
check("cape list empty before any fetch", not gallery.list_gallery_capes())

player = gallery.load_player("realplayer")
check("load_player resolves a real player",
      player["id"] == "realplayer" and player["name"] == "RealPlayer", player["id"])
check("real skin + cape present",
      player["has_skin"] and player["has_cape"], str(player))
check("skin preview was rendered", bool(player.get("skin_preview")
      and os.path.isfile(player["skin_preview"])), str(player.get("skin_preview")))

items = gallery.list_gallery_skins()
check("cached player shows in the (network-free) skin catalog",
      any(i["id"] == "realplayer" and i["name"] == "RealPlayer"
          and os.path.isfile(i["sheet_path"]) for i in items),
      str([i.get("id") for i in items]))

cape_items = gallery.list_gallery_capes()
check("cached player's cape shows in the cape catalog",
      any(i["id"] == "realplayer" and os.path.isfile(i["sheet_path"]) for i in cape_items))

# 2. Caching: fresh short-circuit + stale offline fallback
# --------------------------------------------------------
_hits["n"] = 0
snap_a = remotes.ensure_player("realplayer")          # fresh cache -> no network
check("fresh cache short-circuits the network", _hits["n"] == 0, str(_hits["n"]))
check("cached snapshot still has the art", bool(snap_a and snap_a["skin_path"]))

prof = remotes._load_profile("realplayer")
prof["fetched_at"] = 0                                # ancient
with open(remotes._profile_path("realplayer"), "w", encoding="utf-8") as f:
    json.dump(prof, f)
remotes.TEST_HANDLER = lambda url: (_ for _ in ()).throw(RuntimeError("offline"))
snap_b = remotes.ensure_player("realplayer")
check("offline with stale cache still returns a snapshot",
      bool(snap_b and snap_b["skin_path"]), str(snap_b))
remotes.TEST_HANDLER = lambda url: _handler(url, cape=True)

# 3. Install flows (real player -> your own skin/cape, worn immediately)
# ---------------------------------------------------------------------
cfg = {"username": "tester"}

entry = gallery.install_gallery_skin(cfg, "realplayer")
check("real skin registers in skins meta",
      any(x["filename"] == entry["filename"] for x in skins.list_custom_skins()))
check("real skin becomes the active skin", cfg.get("active_skin") == entry["filename"])
check("skin sync wrote LocalSkin/<USERNAME>.png",
      os.path.isfile(os.path.join(skins.CSL_LOCAL_SKINS_DIR, "tester.png")))
check("installed skin maps back to its player id",
      gallery.gallery_id_for_file("skin", entry["filename"]) == "realplayer")

entry_c = gallery.install_gallery_cape(cfg, "realplayer")
check("real cape registers in capes meta",
      any(x["filename"] == entry_c["filename"] for x in capes.list_custom_capes()))
check("real cape becomes the active cape", cfg.get("active_cape") == entry_c["filename"])
check("cape sync wrote LocalSkin/capes/<USERNAME>.png",
      os.path.isfile(os.path.join(capes.CSL_LOCAL_CAPES_DIR, "tester.png")))
check("installed cape maps back to its player id",
      gallery.gallery_id_for_file("cape", entry_c["filename"]) == "realplayer")

entry2 = gallery.install_gallery_cape(cfg, "realplayer")
check("re-installing the same cape works", cfg.get("active_cape") == entry2["filename"])
check("mapping follows the newest install",
      gallery.gallery_id_for_file("cape", entry2["filename"]) == "realplayer")

# 5. Honest failures + bookkeeping round-trip
# -------------------------------------------
remotes.TEST_HANDLER = lambda url: (_ for _ in ()).throw(RuntimeError("offline"))
raised = False
try:
    gallery.load_player("no-such-player")
except ValueError:
    raised = True
check("unresolvable player raises ValueError (honest)", raised)


def cape_less_handler(url):
    if "users/profiles" in url:
        return json.dumps({"id": U, "name": "RealPlayer"}).encode()
    if "/session" in url:
        return _tex_payload(cape=False)
    if "textures.minecraft.net/texture/aaaa" in url:
        return SKIN_BYTES
    raise RuntimeError("cape-less fake server unexpected url: " + url)


remotes.TEST_HANDLER = cape_less_handler
p2 = gallery.load_player("realplayer", force=True)
check("cape-less player reported honestly",
      p2["has_skin"] and not p2["has_cape"], str(p2))
raised = False
try:
    gallery.install_gallery_cape(cfg, "realplayer")
except ValueError:
    raised = True
check("installing a cape the player doesn't have raises ValueError", raised)
remotes.TEST_HANDLER = lambda url: _handler(url, cape=True)

capes.delete_custom_cape(entry_c["filename"]); gallery.forget_file("cape", entry_c["filename"])
check("forget clears a deleted cape's mapping",
      gallery.gallery_id_for_file("cape", entry_c["filename"]) is None)
skins.delete_custom_skin(entry["filename"]); gallery.forget_file("skin", entry["filename"])
check("forget clears a deleted skin's mapping",
      gallery.gallery_id_for_file("skin", entry["filename"]) is None)
gallery.forget_file("cape", entry_c["filename"])
check("forget is safe to call twice", True)

# 6. Fuzzy search + curated recommendations (all network-free)
# ------------------------------------------------------------
check("featured list is curated and capped sensibly",
      0 < gallery.featured_count() <= 30, str(gallery.featured_count()))

# Normalisation ignores case + punctuation, so these all collapse to one token.
check("_norm strips case and punctuation",
      gallery._norm("Captain_Sparklez") == gallery._norm("captain sparklez")
      == "captainsparklez")

# A typo drops a vowel; subsequence matching still finds the player.
fuzzy = gallery.list_gallery_skins("realplayr")
check("fuzzy (subsequence) query finds the player",
      any(i["id"] == "realplayer" for i in fuzzy),
      str([i["id"] for i in fuzzy]))
check("nonsense query matches nothing", not gallery.list_gallery_skins("zzqqxx"))
check("query is applied before limit",
      all(i["id"] == "realplayer" for i in gallery.list_gallery_skins("real", limit=1)))

# The exact-name Mojang API can't do typos; suggest_player is the wrapper that
# turns a miss into a "did you mean". It returns the exact casing of the match.
check("suggest_player recovers from a typo",
      gallery.suggest_player("realplayr") == "RealPlayer",
      str(gallery.suggest_player("realplayr")))
check("suggest_player ignores unrelated input",
      gallery.suggest_player("qqzzxx") is None)

# The curated tags power the search and the cape catalog.
check("featured tags are exposed for search",
      "cape" in remotes.featured_tags("jeb_") and
      remotes.featured_tags("nobody-here") == [])

# A search must offer suggestions even before the background prefetch has
# cached them, or a fresh install returns "nothing matches" for every name.
sugg = gallery.list_gallery_skins("jeb")
check("search surfaces a not-yet-cached featured player",
      any(i["id"] == "jeb_" and not i.get("cached") for i in sugg),
      str([(i["id"], i.get("cached")) for i in sugg]))
check("recommended (no-query) view stays cached-only",
      all(i.get("cached") for i in gallery.list_gallery_skins()))

# Cape suggestions only include featured players we know own a cape.
cape_sugg = gallery.list_gallery_capes("notch")
check("cape search excludes featured players without a cape",
      not any(i["id"] == "notch" for i in cape_sugg),
      str([i["id"] for i in cape_sugg]))
cape_sugg2 = gallery.list_gallery_capes("grian")
check("cape search surfaces a cape-owning featured player",
      any(i["id"] == "Grian" for i in cape_sugg2),
      str([i["id"] for i in cape_sugg2]))

# Summary
# -------
failed = [c for c in _checks if not c[1]]
print(f"\n{len(_checks) - len(failed)} passed, {len(failed)} failed")
sys.exit(1 if failed else 0)
