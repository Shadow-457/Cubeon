"""
Milestones: earn hats by actually using the launcher.

WHY A SEPARATE MODULE AND FILE
Counters like "seconds played" update constantly; config.json is rewritten
wholesale on every settings change by whichever thread holds no lock (known
Critical bugs #1/#2 in agents/docs/bugs-and-flaws.md), so parking a hot
counter there would amplify both. skin_net.json and window_geometry.json
already established the precedent: hot or self-contained state lives in its
own tiny file under ~/.cubeon_launcher/. This one is milestones.json.

KV BUDGET (the design constraint, 2026-09-06 kv-quota-storm)
The skins Worker's KV namespace allows 1,000 writes/day ACCOUNT-WIDE (all
workers share it) but 100k reads/day. So:
  - counters and unlock truth live LOCALLY (milestones.json); the Worker is
    only a cross-install backup of the unlock ledger.
  - each unlock costs exactly ONE write ever: the merged "unlocks:<uuid>"
    key is PUT only when it gains an id (putIfChanged; re-posting the same
    set = zero writes).
  - reads are cached (the whole ledger is one small GET, fetched at most
    once per session).
  - no timestamps, no history, no per-milestone keys - the ledger is a
    comma-joined id list so it never grows with playtime.

BACKDATING "early adopter"
Existing installs reached first_run before this feature existed (config has
`onboarded` but no date). first_seen_at is seeded on first load: now for new
installs; for installs that already have `onboarded` set we can't know the
real date, so we deliberately DO NOT grandfather the Founder hat - guessing
dates would hand it to a reinstall as easily as a veteran. The launch date
of the feature itself is the cutoff, stored once in the state file.
"""
import json
import os
import threading
import time

from .paths import CUBEON_HOME

MILESTONES_PATH = os.path.join(CUBEON_HOME, "milestones.json")

# The feature's launch date (UTC epoch). "Early adopter" = first_seen_at
# before this. Bump ONLY if you relaunch the program intentionally - it is
# recorded into each user's state file on first load, after which the
# per-user copy is authoritative (a later bump doesn't move the goalposts).
FOUNDER_CUTOFF = 1790000000  # 2026-09-17, feature rollout

# Milestone definitions. `kind` is one of the counter sources below; the
# ids here must match earnable hats declared in cubeon/cosmetics.py.
MILESTONES = [
    {"id": "founder",  "kind": "early_adopter", "name": "Founder",
     "desc": "Played Cubeon in its first weeks"},
    {"id": "veteran",  "kind": "hours_played",  "goal": 10, "name": "Veteran",
     "desc": "10 hours in game"},
    {"id": "party",    "kind": "friends",       "goal": 3,  "name": "Party",
     "desc": "3 friends on Cubeon"},
    {"id": "host",     "kind": "hosted",        "goal": 1,  "name": "Host",
     "desc": "Host a world or server for friends"},
]

_lock = threading.Lock()
_state = None  # cached dict once loaded


def _defaults() -> dict:
    return {
        "first_seen_at": time.time(),
        "founder_cutoff": FOUNDER_CUTOFF,
        "seconds_played": 0,
        "sessions_hosted": 0,
        "friends_count_high": 0,
        "unlocked": [],          # milestone ids, in unlock order
        "synced_unlocked": [],   # what the Worker last confirmed
        "last_sync": 0.0,
        "retry_not_before": 0.0,  # quota backoff for the ledger sync
    }


def load_state() -> dict:
    """Loads (and caches) the milestone state, seeding a new file on first
    run. Existing installs with `onboarded` but no milestones.json get
    their first_seen_at NOW - see the module docstring for why that's the
    honest choice."""
    global _state
    with _lock:
        if _state is not None:
            return _state
        data = None
        try:
            with open(MILESTONES_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            data = None
        base = _defaults()
        if isinstance(data, dict):
            for k in base:
                if k in data:
                    base[k] = data[k]
        base["unlocked"] = [u for u in base.get("unlocked", [])
                            if isinstance(u, str)]
        base["synced_unlocked"] = [u for u in base.get("synced_unlocked", [])
                                   if isinstance(u, str)]
        _state = base
        if data is None:
            _save_state_locked()
        return _state


def save_state() -> None:
    """Persists the cached state. Called by every mutator; cheap (a few
    hundred bytes) and safe to call from any thread (serialized by _lock)."""
    with _lock:
        _save_state_locked()


def _save_state_locked() -> None:
    """Writer half for callers that already hold _lock (load_state's seed
    path) - _lock is NOT reentrant, so save_state() would self-deadlock."""
    if _state is None:
        return
    tmp = MILESTONES_PATH + ".tmp"
    try:
        os.makedirs(CUBEON_HOME, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_state, f, indent=2)
        os.replace(tmp, MILESTONES_PATH)  # atomic, unlike config.json
    except OSError:
        pass


def _progress_locked(m: dict, st: dict) -> tuple[float, float]:
    """(current, goal) for a milestone against an ALREADY-HELD state dict.
    Callers must hold _lock (or own st privately, like the test harness).
    Goal-normalized so goal>0; current may exceed goal ("unlocked, keep
    counting" for the UI bar)."""
    goal = float(m.get("goal", 1) or 1)
    if m["kind"] == "early_adopter":
        # Binary: 1.0 if adopted before the cutoff, else 0.
        return (1.0 if st["first_seen_at"] < st.get("founder_cutoff",
                                                    FOUNDER_CUTOFF) else 0.0), 1.0
    if m["kind"] == "hours_played":
        return st["seconds_played"] / 3600.0, goal
    if m["kind"] == "friends":
        return float(st["friends_count_high"]), goal
    if m["kind"] == "hosted":
        return float(st["sessions_hosted"]), goal
    return 0.0, goal


def progress(m: dict) -> tuple[float, float]:
    """Lock-safe (current, goal) for the UI's progress bars. Reads the
    cached state under the lock but never re-enters load_state() (whose
    own locking would self-deadlock)."""
    if _state is None:
        load_state()  # cold path: seed outside the lock below
    with _lock:
        return _progress_locked(m, _state)


def evaluate() -> list[str]:
    """Checks every milestone against the counters and records (once, in
    order) any that newly crossed. Returns the NEWLY unlocked ids so the
    caller can toast; already-unlocked ones return nothing. One call = at
    most one local save, and each new unlock triggers at most one deferred
    KV write via sync_unlocks."""
    st = load_state()
    fresh = []
    with _lock:
        have = set(st["unlocked"])
        for m in MILESTONES:
            if m["id"] in have:
                continue
            cur, goal = _progress_locked(m, st)
            if cur >= goal:
                st["unlocked"].append(m["id"])
                fresh.append(m["id"])
        if fresh:
            _save_state_locked()
    # Sync on a fresh unlock OR when a previous sync never confirmed the
    # whole local set (e.g. it hit the daily KV quota and backed off).
    # Write-frugal: a healthy sync costs at most ONE merge write, ever;
    # retries are rate-limited by retry_not_before inside sync_unlocks().
    if fresh or set(st["unlocked"]) - set(st["synced_unlocked"]):
        sync_unlocks()  # fire-and-forget background thread
    return fresh


def is_unlocked(milestone_id: str) -> bool:
    if _state is None:
        load_state()  # cold path outside the lock
    with _lock:
        return milestone_id in _state["unlocked"]


# --------------------------------------------------------------------- feeds

def add_play_seconds(seconds: float) -> None:
    """Accumulates in-game time. Called from the game's on_exit hook with
    the wall-clock duration of the session (see main.py). Clamped to sane
    bounds so a broken clock can't mint a Veteran hat."""
    if not isinstance(seconds, (int, float)) or seconds <= 0:
        return
    seconds = min(float(seconds), 24 * 3600.0)  # one marathon day max
    st = load_state()
    with _lock:
        st["seconds_played"] += seconds
        _save_state_locked()


def add_hosted_session() -> None:
    """A world hosted for friends (P2P) or a server started on the Server
    tab counted once per (start -> clean exit) cycle."""
    st = load_state()
    with _lock:
        st["sessions_hosted"] += 1
        _save_state_locked()


def note_friends_count(count: int) -> None:
    """Records the high-water mark of the roster size. High-water (not
    current) so unfriending doesn't claw back an earned hat."""
    if not isinstance(count, int) or count <= 0:
        return
    st = load_state()
    with _lock:
        if count > st["friends_count_high"]:
            st["friends_count_high"] = count
            _save_state_locked()


# ------------------------------------------------------------------ sync

def _worker_unlocks_url():
    from . import csl
    return csl.CUBEON_API_BASE + "/api/unlocks"


def sync_unlocks() -> None:
    """Pushes the local unlock set to the Worker (daemon thread, best
    effort). One POST that carries the full local set; the Worker merges
    into unlocks:<uuid> and only writes when the set GREW - so a steady
    state or a re-post costs zero writes. Also pulls the server's set back
    and unions it locally (cross-install recovery: a reinstall that lost
    milestones.json but kept auth_key.json gets its hats back)."""
    st = load_state()
    if time.time() < st.get("retry_not_before", 0.0):
        return  # recent quota exhaustion - wait for the daily KV window
    threading.Thread(target=_sync_unlocks_blocking, daemon=True,
                     name="cubeon-milestones-sync").start()


def _note_sync_quota_exhausted() -> None:
    """Records the backoff after a 429 (daily KV window). Never raises."""
    st = load_state()
    with _lock:
        st["retry_not_before"] = next_sync_retry_not_before()
        _save_state_locked()


def _sync_unlocks_blocking() -> None:
    try:
        import requests
        from .config import stable_uuid, stable_secret
        st = load_state()
        local = set(st["unlocked"])
        headers = {"Authorization": f"Bearer {stable_secret()}"}
        resp = requests.post(
            _worker_unlocks_url(),
            json={"uuid": stable_uuid(),
                  "milestones": sorted(local)},
            headers=headers, timeout=8.0,
        )
        if resp.status_code == 429:
            # Daily KV budget drained account-wide. The Worker returns the
            # CURRENT set with quota-failure semantics, so a plain success
            # path here would wrongly mark everything as synced. Back off
            # until the window rolls instead.
            _note_sync_quota_exhausted()
            return
        if resp.status_code != 200:
            return  # offline/server trouble: local truth stands
        server = set(resp.json().get("milestones", []))
        if local and not server:
            # 200-but-empty echo: the Worker's quota path answers the same
            # 200 shape with the un-persisted (old) set, so a first-unlock
            # POST during a drained window looks exactly like this. Treat it
            # as quota-shaped: back off to the daily-window retry rather
            # than marking our set as synced.
            _note_sync_quota_exhausted()
            return
        if server - local:
            # Server knew hats this install hadn't earned locally (reinstall
            # or a second machine). Union them in - they WERE earned.
            with _lock:
                st["unlocked"] = list(local | server)
                _save_state_locked()
        if server != set(st["synced_unlocked"]):
            with _lock:
                st["synced_unlocked"] = sorted(server)
                st["last_sync"] = time.time()
                _save_state_locked()
    except Exception:
        pass  # purely cosmetic; never disturb the caller


def next_sync_retry_not_before() -> float:
    """When a quota-exhausted sync may be retried (UTC epoch). The ledger
    POST is indistinguishable from success on a 429 (the Worker returns the
    current server set with 200 semantics), so the client backs off until
    the KV daily window rolls (00:00 UTC) plus a margin, instead of
    hammering a drained budget on every evaluate()."""
    now = time.time()
    tomorrow_utc = (now // 86400 + 1) * 86400
    return tomorrow_utc + 900  # :15 past, so we're not first in line at rollover
