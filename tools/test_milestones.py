#!/usr/bin/env python3
"""
Tests for cubeon/milestones.py + the earnable-hat gating in
cubeon/cosmetics.py - run with:

    python tools/test_milestones.py

No network, no real HOME: the sandbox points HOME (and thus
~/.cubeon_launcher) at a temp dir, and the Worker sync is exercised with a
stubbed requests module that records the POST and returns a canned ledger.

Contracts worth keeping pinned here:

  * the KV-budget shape: evaluate() only fires a sync when something NEW
    unlocked, and the sync POSTs the full local set once (the Worker merges
    and writes only on growth - see worker/test-worker.mjs for that side),
  * milestones can never un-earn (friend count is a high-water mark),
  * set_hat() refuses locked hats with PermissionError and still allows
    freely-wearable ones,
  * a worn hat keeps rendering even if the milestone state was lost
    (compose stays defensive; enforcement is at wear-time only),
  * playtime is clamped (a broken clock can't mint a Veteran hat).
"""
import json
import os
import sys
import tempfile
import threading
import time

# --- Sandbox: temp HOME before importing anything of ours --------------------
_tmp = tempfile.mkdtemp(prefix="cubeon-milestones-test-")
os.environ["HOME"] = _tmp
os.environ["USERPROFILE"] = _tmp

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

passed = failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok   {label}")
    else:
        failed += 1
        print(f"  FAIL {label}" + (f"  [{detail}]" if detail else ""))


# --- stub requests BEFORE milestones can import it ---------------------------
class _FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeRequests:
    """Records POSTs so tests can assert the write-frugality contract."""
    def __init__(self):
        self.posts = []
        self.response = _FakeResp(200, {"milestones": []})

    def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append({"url": url, "json": json, "headers": headers})
        return self.response


import types
fake_requests = _FakeRequests()
sys.modules["requests"] = types.SimpleNamespace(RequestException=Exception,
                                                post=fake_requests.post)

from cubeon import milestones
from cubeon import cosmetics

MILESTONES_PATH = os.path.join(_tmp, ".cubeon_launcher", "milestones.json")


def fresh_state(**over):
    """Reset the module singleton to a known state (no file I/O).
    first_seen_at defaults to AFTER the founder cutoff so founder only
    unlocks in the section that explicitly tests it."""
    milestones._state = {
        "first_seen_at": milestones.FOUNDER_CUTOFF + 100,
        "founder_cutoff": milestones.FOUNDER_CUTOFF,
        "seconds_played": 0.0,
        "sessions_hosted": 0,
        "friends_count_high": 0,
        "unlocked": [],
        "synced_unlocked": [],
        "last_sync": 0.0,
        "retry_not_before": 0.0,
        **over,
    }
    return milestones._state


def drain_sync():
    """Wait for any sync_unlocks daemon thread to finish so posts are countable."""
    deadline = time.time() + 5
    while time.time() < deadline:
        if not any(t.name == "cubeon-milestones-sync"
                   for t in threading.enumerate()):
            return
        time.sleep(0.02)


print("\n1. state file basics")
st = fresh_state()
milestones.save_state()
on_disk = json.load(open(MILESTONES_PATH))
check("save_state wrote the seeded file", on_disk["seconds_played"] == 0.0)
loaded = milestones.load_state()
check("load_state returns the cached singleton", loaded is st)
check("atomic write left no .tmp behind",
      not os.path.exists(MILESTONES_PATH + ".tmp"))

print("\n2. evaluate() + unlock bookkeeping")
fresh_state()
check("nothing unlocked at zero", milestones.evaluate() == [])
milestones.add_play_seconds(3600)  # 1 hour
check("1h earns nothing", milestones.evaluate() == [])
milestones.add_play_seconds(9 * 3600)  # 10 total
fresh = milestones.evaluate()
check("10h earns veteran exactly once", fresh == ["veteran"], str(fresh))
check("re-evaluate returns nothing new", milestones.evaluate() == [])
check("is_unlocked(veteran)", milestones.is_unlocked("veteran"))

print("\n3. clamping + high-water marks")
fresh_state()
milestones.add_play_seconds(999 * 3600)
st = milestones.load_state()
check("one absurd session clamped to 24h", st["seconds_played"] == 24 * 3600,
      str(st["seconds_played"]))
milestones.add_play_seconds(-5)
check("negative playtime ignored", milestones.load_state()["seconds_played"] == 24 * 3600)
fresh_state()
milestones.note_friends_count(3)
check("3 friends earns party", milestones.evaluate() == ["party"])
milestones.note_friends_count(1)
check("friend count is high-water (can't un-earn)",
      milestones.load_state()["friends_count_high"] == 3)
check("dropped roster doesn't re-lock", milestones.is_unlocked("party"))

print("\n4. hosting + early adopter")
fresh_state()
milestones.add_hosted_session()
check("1 hosted session earns host", milestones.evaluate() == ["host"])
fresh_state(first_seen_at=milestones.FOUNDER_CUTOFF - 100)
check("first_seen before cutoff earns founder",
      milestones.evaluate() == ["founder"])
fresh_state(first_seen_at=milestones.FOUNDER_CUTOFF + 100)
check("first_seen after cutoff earns nothing",
      "founder" not in milestones.evaluate())

print("\n5. cosmetics gating")
ids = [h["id"] for h in cosmetics.list_hats()]
for want in ("veteran", "party", "host", "founder"):
    check(f"catalogue has earnable hat {want!r}", want in ids)
reqs = {h.get("require") for h in cosmetics.list_hats()}
check("free hats have no require", None in reqs)
check("hat_requirement round-trips",
      cosmetics.hat_requirement("veteran") == "veteran"
      and cosmetics.hat_requirement("tophat") is None)
fresh_state()
check("veteran locked at zero playtime", not cosmetics.hat_unlocked("veteran"))
check("tophat always unlocked", cosmetics.hat_unlocked("tophat"))

cfg = {}
try:
    cosmetics.set_hat(cfg, "veteran")
    wore = True
except PermissionError:
    wore = False
except Exception as ex:
    wore = False
    print("   (unexpected exception type:", type(ex).__name__, ")")
check("set_hat refuses locked hat with PermissionError", not wore)
check("refusal did not record a hat", "cosmetic_hat" not in cfg)
try:
    cosmetics.set_hat(cfg, "tophat")
    free_ok = True
except Exception:
    free_ok = False
check("set_hat still allows free hats", free_ok and cfg.get("cosmetic_hat") == "tophat")

fresh_state()
cfg2 = {"cosmetic_hat": "veteran"}
img = cosmetics.compose_skin_with_hat(cfg2)
check("worn hat keeps rendering even when locked locally",
      img is not None and img.size == (64, 64))

print("\n6. sync write-frugality (KV budget contract)")
fresh_state()
fake_requests.posts.clear()
milestones.evaluate()
drain_sync()
check("no unlock -> no sync POST at all", len(fake_requests.posts) == 0,
      str(len(fake_requests.posts)))
# Un-confirmed unlocks (a prior sync that died on the KV quota) re-sync on
# the next evaluate, not only on a brand-new unlock.
fresh_state(unlocked=["founder"], synced_unlocked=[])
fake_requests.posts.clear()
milestones.evaluate()
drain_sync()
check("unconfirmed unlock re-syncs without a new unlock",
      len(fake_requests.posts) == 1, str(len(fake_requests.posts)))
fresh_state(unlocked=["founder"], synced_unlocked=["founder"])
fake_requests.posts.clear()
milestones.evaluate()
drain_sync()
check("fully confirmed set -> no re-sync POST",
      len(fake_requests.posts) == 0, str(len(fake_requests.posts)))
fresh_state()
milestones.add_play_seconds(10 * 3600)
fake_requests.posts.clear()
milestones.evaluate()
drain_sync()
check("one new unlock -> exactly one POST", len(fake_requests.posts) == 1,
      str(len(fake_requests.posts)))
if fake_requests.posts:
    body = fake_requests.posts[0]["json"]
    check("POST carries uuid + full local set",
          "uuid" in body and body["milestones"] == ["veteran"], str(body))
    check("POST is Bearer-authorized",
          fake_requests.posts[0]["headers"]["Authorization"].startswith("Bearer "))

# Server union: the response's set is merged back (reinstall restore).
fake_requests.response = _FakeResp(200, {"milestones": ["veteran", "party"]})
fresh_state()
fake_requests.posts.clear()
milestones._sync_unlocks_blocking()
check("server-known hats union into local state",
      set(milestones.load_state()["unlocked"]) == {"veteran", "party"},
      str(milestones.load_state()["unlocked"]))

# Quota/offline: non-200 must leave local truth untouched and not raise.
fake_requests.response = _FakeResp(429, {"error": "kv_write_budget_exhausted"})
fresh_state(unlocked=["host"])
try:
    milestones._sync_unlocks_blocking()
    survived = True
except Exception:
    survived = False
check("429 sync never raises", survived)
check("429 sync keeps local unlocks",
      milestones.load_state()["unlocked"] == ["host"])
check("429 sets a daily-window retry backoff",
      milestones.load_state()["retry_not_before"] > time.time())
before = milestones.load_state()["retry_not_before"]
fake_requests.posts.clear()
milestones.sync_unlocks()
drain_sync()
check("backoff suppresses further sync attempts today",
      len(fake_requests.posts) == 0)

# The ambiguous quota shape: 200 but the server echoes an EMPTY set while
# ours is non-empty (a drained Worker can't persist a first unlock).
fake_requests.response = _FakeResp(200, {"milestones": []})
fresh_state(unlocked=["veteran"])
milestones.load_state()["retry_not_before"] = 0.0
milestones._sync_unlocks_blocking()
check("200-but-empty echo treated as quota (backoff set)",
      milestones.load_state()["retry_not_before"] > time.time())
check("200-but-empty doesn't mark unlocks as synced",
      milestones.load_state()["synced_unlocked"] == [])

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
