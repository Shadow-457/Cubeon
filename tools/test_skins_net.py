#!/usr/bin/env python3
"""
Tests for the network-publishing half of cubeon/skins.py - run with:

    python tools/test_skins_net.py

Needs nothing installed and touches no network: it points HOME at a temp
directory, stubs minecraft_launcher_lib, and swaps skins.requests for a fake
that records the call and returns a canned response. So no .minecraft folder,
no Worker, and no real HTTP.

What's worth keeping here is the contract between this client and the Worker
(worker/cubeon-skins.js), because the two are tested separately and a drift
between them is invisible until a real player's skin silently doesn't show:

  * the composed sheet the client uploads must pass the Worker's PNG guard
    (worker_is_skin_png below is that guard, reimplemented from the Worker),
  * writes are Bearer-authorized by THIS machine's secret_token and keyed to
    its persistent public_uuid - never by name,
  * write-frugality only works if the client skips BOTH calls when nothing
    changed (KV writes are scarce): a rename alone costs one heartbeat, a new
    PNG alone costs one upload,
  * a 403 (this UUID is owned by another secret) must be swallowed, not
    retried in a way that spins, and must NOT poison the dedupe marker.
"""
import base64
import hashlib
import json
import os
import sys
import tempfile
import types

import requests as _real_requests

# --- Sandbox: temp HOME + stubbed mll, before importing anything of ours ----
_tmp = tempfile.mkdtemp(prefix="cubeon-skins-net-test-")
os.environ["HOME"] = _tmp
os.environ["USERPROFILE"] = _tmp  # Windows equivalent, for Path.home()

_fake_mc = os.path.join(_tmp, ".minecraft")
_mll = types.ModuleType("minecraft_launcher_lib")
_mll.utils = types.SimpleNamespace(get_minecraft_directory=lambda: _fake_mc)
sys.modules["minecraft_launcher_lib"] = _mll

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cubeon import skins                                            # noqa: E402
from cubeon.config import stable_secret, stable_uuid                # noqa: E402
from PIL import Image                                               # noqa: E402

failures = 0


def check(label, ok, extra=""):
    global failures
    print(f"{'  ok  ' if ok else ' FAIL '} {label}{'  ' + str(extra) if extra else ''}")
    if not ok:
        failures += 1


def worker_is_skin_png(b: bytes) -> bool:
    """worker/cubeon-skins.js isSkinPng(), reimplemented: the 8-byte signature
    plus an IHDR that says 64x64 or legacy 64x32. If the client ever produces
    something this rejects, uploads 400 and no friend sees the skin."""
    sig = bytes([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
    if len(b) < 24 or b[:8] != sig:
        return False
    w = int.from_bytes(b[16:20], "big")
    h = int.from_bytes(b[20:24], "big")
    return (w == 64 and h == 64) or (w == 64 and h == 32)


# --- Fake requests: record the call, return whatever the test lined up -------
_calls = []
_next = {"raise": False}


class _FakeResp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


def _fake_post(url, json=None, headers=None, timeout=None):
    _calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
    if _next["raise"]:
        raise _real_requests.RequestException("simulated network failure")
    return _next["resp"]


# skins.py refers to requests.post / requests.RequestException by the module
# global `requests`, so rebinding that name is enough - and it keeps the real
# RequestException class so the except clause still matches.
skins.requests = types.SimpleNamespace(
    post=_fake_post, RequestException=_real_requests.RequestException,
)


def reset_calls():
    _calls.clear()
    _next["raise"] = False


def clear_marker():
    skins._save_publish_state({})


def bearer_of(call):
    """The raw token out of a recorded call's Authorization header."""
    header = (call.get("headers") or {}).get("Authorization", "")
    return header[len("Bearer "):] if header.startswith("Bearer ") else None


def ok_all():
    _next["resp"] = _FakeResp(200, {"ok": True})


# ---------------------------------------------------------------------------
# 1. The client<->Worker PNG contract: a composed sheet is a valid skin PNG
# ---------------------------------------------------------------------------
_content_src = os.path.join(_tmp, "content.png")
Image.new("RGBA", (64, 64), (200, 100, 100, 255)).save(_content_src)
_content = skins.add_custom_skin(_content_src, "Content")

default_cfg = {"username": "TestUser", "active_skin": _content["filename"],
               "cosmetic_hat": None, "manage_skin_mod": True}
png = skins._composed_skin_png(default_cfg)
check("composed sheet passes the Worker's PNG guard", worker_is_skin_png(png),
      f"{len(png)}B")
check("composed sheet is well under the 24KB skin cap", len(png) < 24 * 1024, f"{len(png)}B")

# ---------------------------------------------------------------------------
# 2. Happy path WITH content: first publish fires heartbeat THEN upload
#
# default_cfg carries a real uploaded skin - a no-skin/no-hat player must NOT
# upload anything (see section 5), so the full two-call contract needs actual
# custom content.
# ---------------------------------------------------------------------------
clear_marker()
reset_calls()
ok_all()
skins._publish_skin(default_cfg)

check("first publish makes exactly two POSTs (heartbeat + upload)", len(_calls) == 2, len(_calls))
hb = _calls[0] if _calls else {}
up = _calls[1] if len(_calls) > 1 else {}
check("heartbeat goes to the heartbeat URL", hb.get("url") == skins._HEARTBEAT_URL)
check("upload goes to the skin URL", up.get("url") == skins._UPLOAD_URL)
check("both calls pass a timeout (can't hang forever)",
      hb.get("timeout") == skins._NET_TIMEOUT and up.get("timeout") == skins._NET_TIMEOUT)

check("heartbeat body carries the in-game username", hb.get("json", {}).get("username") == "TestUser")
check("heartbeat body carries THIS machine's public_uuid", hb.get("json", {}).get("uuid") == stable_uuid())
check("heartbeat is Bearer-authorized by the private token",
      bearer_of(hb) == stable_secret())
check("the private token NEVER rides in a request body",
      "secret" not in hb.get("json", {}) and "secret_token" not in hb.get("json", {}))

upload_body = up.get("json", {})
check("upload body carries the master UUID, not the name",
      upload_body.get("uuid") == stable_uuid() and "username" not in upload_body)
check("upload is Bearer-authorized by the same private token",
      bearer_of(up) == stable_secret())
check("opaque-arm custom skin uploads as classic model", upload_body.get("model") == "default")

decoded = base64.b64decode(upload_body.get("skin", ""))
check("body skin decodes to a valid skin PNG", worker_is_skin_png(decoded))
marker = skins._load_publish_state()
check("marker hash matches the exact bytes uploaded",
      marker.get("hash") == hashlib.sha256(decoded).hexdigest())
check("marker records name, uuid, model and endpoint base",
      marker.get("username") == "TestUser" and marker.get("uuid") == stable_uuid()
      and marker.get("model") == "default"
      and marker.get("base") == skins.csl.CUBEON_API_BASE)

# ---------------------------------------------------------------------------
# 3. Write-frugality: nothing changed => zero calls; each drift costs exactly
# one targeted call
#
# This is load-bearing, not a nicety: without it, every launch would burn KV
# writes re-sending the same data, and free-tier writes are the scarce resource.
# ---------------------------------------------------------------------------
reset_calls()
ok_all()
skins._publish_skin(default_cfg)
check("unchanged identity+skin makes NO calls at all", _calls == [], len(_calls))

# A stale content hash forces ONLY an upload (identity pointer didn't move).
marker["hash"] = "deadbeef"
skins._save_publish_state(marker)
reset_calls()
ok_all()
skins._publish_skin(default_cfg)
check("a stale content hash forces exactly one upload (no heartbeat)",
      len(_calls) == 1 and _calls[0]["url"] == skins._UPLOAD_URL, len(_calls))

# A rename forces ONLY a heartbeat (same machine, same skin under the same UUID).
reset_calls()
ok_all()
skins._publish_skin({**default_cfg, "username": "RenamedUser"})
check("rename fires exactly one heartbeat (no re-upload)",
      len(_calls) == 1 and _calls[0]["url"] == skins._HEARTBEAT_URL
      and _calls[0]["json"]["username"] == "RenamedUser", len(_calls))
check("rename heartbeat still carries the SAME public_uuid",
      _calls and _calls[0]["json"]["uuid"] == stable_uuid())

# A marker left by a *different* endpoint (a future API-base move) suppresses
# nothing: the identity half re-syncs to the current one, while an unchanged
# sheet correctly costs no re-upload.
skins._save_publish_state({"username": "TestUser", "uuid": stable_uuid(),
                           "model": "default", "hash": hashlib.sha256(png).hexdigest(),
                           "base": "https://old-worker.example"})
reset_calls()
ok_all()
skins._publish_skin(default_cfg)
check("a marker from a different endpoint re-syncs the pointer (no needless upload)",
      len(_calls) == 1 and _calls[0]["url"] == skins._HEARTBEAT_URL, len(_calls))

# ---------------------------------------------------------------------------
# 4. Failure handling: 403 and network errors are swallowed, don't poison state
# ---------------------------------------------------------------------------
clear_marker()
reset_calls()
_next["resp"] = _FakeResp(403, {"error": "not_yours"})
skins._publish_skin(default_cfg)  # must not raise
check("a 403 on the heartbeat stops everything (one attempt)", len(_calls) == 1)
check("a 403 does NOT record a marker (so a later fix retries)",
      skins._load_publish_state() == {})

# A 403 on the upload (after a successful heartbeat) keeps the identity half.
clear_marker()
reset_calls()
_next["raise"] = False
_responses_list = [_FakeResp(200, {"status": "ok"}), _FakeResp(403, {"error": "not_yours"})]
_seq = {"n": 0}
def _sequenced_post(url, json=None, headers=None, timeout=None):
    _seq["n"] += 1
    _calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
    if _next["raise"]:
        raise _real_requests.RequestException("simulated network failure")
    return _responses_list[_seq["n"] - 1]
_orig_post = skins.requests.post
skins.requests.post = _sequenced_post
try:
    skins._publish_skin(default_cfg)  # must not raise
finally:
    skins.requests.post = _orig_post
state = skins._load_publish_state()
check("heartbeat success survives an upload failure (identity half recorded)",
      state.get("username") == "TestUser" and state.get("uuid") == stable_uuid(),
      json.dumps(state))
check("failed upload leaves no hash in the marker (retried next sync)",
      state.get("hash") is None and len(_calls) == 2)

clear_marker()
reset_calls()
_next["raise"] = True
skins._publish_skin(default_cfg)  # offline: must return quietly, never raise
check("a network error is swallowed (no raise)", True)
check("a network error records no marker", skins._load_publish_state() == {})

# A missing username is a no-op, never a POST.
reset_calls()
_next["raise"] = False
skins._publish_skin({"username": "", "active_skin": None})
check("empty username never uploads", _calls == [])

# ---------------------------------------------------------------------------
# 5. A VANILLA player (no skin, no hat): heartbeat only, never an upload
#
# The whole point of the pointer: a default-Steve Cubeon player heartbeats on
# first launch, which creates pointer:<name> -> <uuid> - and that pointer is
# what makes serveProfile hand them the shared cape. But they must NOT upload
# a Steve sheet: that would burn KV writes re-shipping a texture everyone has,
# and make the Worker serve Steve-as-a-skin instead of a clean cape-only
# profile.
# ---------------------------------------------------------------------------
vanilla_cfg = {"username": "VanillaUser", "active_skin": None,
               "cosmetic_hat": None}
clear_marker()
reset_calls()
ok_all()
skins._publish_skin(dict(vanilla_cfg))
check("vanilla first launch fires exactly ONE call", len(_calls) == 1, len(_calls))
check("that call is the heartbeat", _calls and _calls[0]["url"] == skins._HEARTBEAT_URL)
check("no POST /api/skin without custom content",
      all(c["url"] != skins._UPLOAD_URL for c in _calls))
state = skins._load_publish_state()
check("vanilla marker records identity but no content hash",
      state.get("username") == "VanillaUser" and state.get("uuid") == stable_uuid()
      and state.get("hash") is None, json.dumps(state))

reset_calls()
ok_all()
skins._publish_skin(dict(vanilla_cfg))
check("second vanilla launch costs ZERO calls (write-frugal)", _calls == [], len(_calls))

reset_calls()
ok_all()
skins._publish_skin({**vanilla_cfg, "username": "RenamedVanilla"})
check("a vanilla rename fires exactly one heartbeat",
      len(_calls) == 1 and _calls[0]["url"] == skins._HEARTBEAT_URL
      and _calls[0]["json"]["username"] == "RenamedVanilla")

# A player who ADDS a skin after being vanilla uploads it (heartbeat already
# done, so exactly one upload call).
skins._save_publish_state({"username": "LateSkin", "uuid": stable_uuid(),
                           "base": skins.csl.CUBEON_API_BASE})
hat_cfg = {"username": "LateSkin", "active_skin": None, "cosmetic_hat": "somehat.png"}
reset_calls()
ok_all()
# cosmetic_hat truthy -> has_custom True; stub the compose to a tiny valid PNG
# instead of relying on hat template assets.
_orig_compose = skins.cosmetics.compose_skin_with_hat
skins.cosmetics.compose_skin_with_hat = lambda cfg: Image.new("RGBA", (64, 64), (1, 2, 3, 255))
try:
    skins._publish_skin(hat_cfg)
finally:
    skins.cosmetics.compose_skin_with_hat = _orig_compose
uploads = [c for c in _calls if c["url"] == skins._UPLOAD_URL]
heartbeats = [c for c in _calls if c["url"] == skins._HEARTBEAT_URL]
check("adding content later triggers ONLY the upload (no duplicate heartbeat)",
      len(uploads) == 1 and heartbeats == [], f"hb={len(heartbeats)} up={len(uploads)}")

# ---------------------------------------------------------------------------
# 6. Slim vs classic model is read from the stored skin metadata
# ---------------------------------------------------------------------------
classic_src = os.path.join(_tmp, "classic.png")
Image.new("RGBA", (64, 64), (200, 100, 100, 255)).save(classic_src)  # opaque = classic
classic = skins.add_custom_skin(classic_src, "Classic")

slim_src = os.path.join(_tmp, "slim.png")
slim_img = Image.new("RGBA", (64, 64), (100, 100, 200, 255))
slim_img.putpixel((47, 20), (0, 0, 0, 0))  # the transparent arm column = slim (Alex)
slim_img.save(slim_src)
slim = skins.add_custom_skin(slim_src, "Slim")

check("no active skin -> classic model", skins._active_skin_is_slim(None) is False)
check("unknown filename -> classic model", skins._active_skin_is_slim("nope.png") is False)
check("opaque-arm skin reads as classic", skins._active_skin_is_slim(classic["filename"]) is False)
check("transparent-arm skin reads as slim", skins._active_skin_is_slim(slim["filename"]) is True)

# The slim flag reaches the upload body as model:"slim".
clear_marker()
reset_calls()
ok_all()
skins._publish_skin({"username": "SlimUser", "active_skin": slim["filename"],
                     "cosmetic_hat": None, "manage_skin_mod": True})
uploads = [c for c in _calls if c["url"] == skins._UPLOAD_URL]
check("slim skin uploads model:'slim'", uploads and uploads[0]["json"]["model"] == "slim")

# ---------------------------------------------------------------------------
# 6. report_skin: posts, reports outcomes honestly, refuses empty names
# ---------------------------------------------------------------------------
reset_calls()
_next["resp"] = _FakeResp(200, {"ok": True})
ok = skins.report_skin("BadActor", "inappropriate")
check("report POSTs to the report URL", _calls and _calls[0]["url"] == skins._REPORT_URL)
check("report body carries username + reason",
      _calls and _calls[0]["json"] == {"username": "BadActor", "reason": "inappropriate"})
check("report returns True on 200", ok is True)

reset_calls()
_next["resp"] = _FakeResp(200, {"ok": True})
check("report omits an empty reason",
      skins.report_skin("BadActor") is True and "reason" not in _calls[0]["json"])

reset_calls()
_next["raise"] = True
check("report returns False on a network error", skins.report_skin("BadActor") is False)

reset_calls()
_next["raise"] = False
check("report refuses an empty username without a POST",
      skins.report_skin("  ") is False and _calls == [])

# ---------------------------------------------------------------------------
# 7. Wiring: sync_local_skin_to_csl publishes iff managed AND there's something
#    to show. (Publish is stubbed here so the real daemon thread never runs -
#    section 2 already proved _publish_skin itself.)
# ---------------------------------------------------------------------------
published = []
skins._publish_skin_async = lambda cfg: published.append(dict(cfg))

skins.sync_local_skin_to_csl({"username": "Wired", "active_skin": classic["filename"],
                              "cosmetic_hat": None, "manage_skin_mod": True})
check("sync publishes when managed and a skin is set", len(published) == 1, len(published))

published.clear()
skins.sync_local_skin_to_csl({"username": "Wired", "active_skin": classic["filename"],
                              "cosmetic_hat": None, "manage_skin_mod": False})
check("sync does NOT publish when skin-mod management is off", published == [])

published.clear()
skins.sync_local_skin_to_csl({"username": "Empty", "active_skin": None,
                              "cosmetic_hat": None, "manage_skin_mod": True})
check("sync DOES publish for a vanilla player too (heartbeat -> pointer -> cape)",
      len(published) == 1, len(published))

published.clear()
skins.sync_local_skin_to_csl({"username": "", "active_skin": None,
                              "cosmetic_hat": None, "manage_skin_mod": True})
check("sync never publishes without a username", published == [])

print(f"\n{failures} CHECK(S) FAILED" if failures else "\nALL SKIN-NET CHECKS PASSED")
sys.exit(1 if failures else 0)
