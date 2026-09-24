"""
Friends service - the headless owner of the social/P2P layer.

WHY THIS EXISTS

All of this logic used to live inside ui/friends_tab.py, wired directly to Flet
controls: a toast was a SnackBar, "something changed" was page.update(), and the
P2P state machine read and wrote a dict that only the tab could see. The Friends
tab is gone; the UI is now a Fabric mod that draws Minecraft's own widgets and
talks to the launcher over the localhost bridge (cubeon/local_api.py). So the
logic needed a home that has no opinion about how it's drawn, and this is it.

The port is deliberately mechanical - same state strings, same message texts,
same threading - because the P2P handshake is a *protocol* between two Cubeon
builds. Changing when a signal goes out or what a state is called breaks
interop with a friend running yesterday's launcher, so nothing here was
"cleaned up" on the way over.

Two substitutions replace the whole UI half:

  * toast(text, error=...)  ->  _notify(text, error=...), which appends to a
    bounded in-memory event log the mod drains with events_since(). A dropped
    notification is a lost notification: the mod has no other way to hear that
    a friend request arrived or that the relay took over.
  * render_roster() / render_p2p_banner() / page.update() / set_conn() /
    show_view()  ->  _changed(), which bumps a revision counter. The mod polls
    (GET /friends, GET /status), so there is nothing to push - a repaint is
    just "the answer to those two endpoints may be different now".

THREADING

Callbacks arrive on the FriendsClient's WebSocket thread; the punch/mod-sync/
asset-sync/watchdog/launch workers are their own daemon threads; and every
public action can be called from a local_api HTTP request thread. So: the
session dict *reference* and the pending-invite map live behind an RLock (six
threads used to swap that reference with no lock at all), and the event log has
its own lock. The state machine itself is NOT globally atomic - it never was -
it stays correct the way it always did, by re-checking room/state before acting
on a session it may no longer own.
"""

import collections
import json
import logging
import os
import threading
import time

from cubeon import e2ee
from cubeon import friends
from cubeon import p2p
from cubeon import worldgate
from cubeon.paths import CUBEON_HOME

log = logging.getLogger(__name__)

# The mod polls, so events only need to survive long enough to be collected.
# A bounded ring means a multi-hour session can't grow the launcher's memory.
_MAX_EVENTS = 200

# One conversation's decrypted-message ring. Bounded for the same reason as the
# event log: the mod polls GET /chat once a second while a chat is open, and an
# unbounded ring would grow forever on a machine left running for a week.
_MAX_CHAT = 200

# The "most recent messages" page size GET /chat serves on a first sync.
_CHAT_PAGE = 40

# History request timeout: if the relay doesn't reply within this many seconds,
# the request is considered failed and will be retried on the next poll.
_HISTORY_REQ_TIMEOUT = 10.0

# Where the decrypted rings persist (chat_store.json). This is the disappearing-
# messages fix: the rings live in memory only, and a launcher restart empties
# them. The relay's stored history CANNOT restore your own sent messages - they
# are E2EE-sealed to the recipient's key (a sender can't decrypt its own
# envelope), so only the live echo ever files them. Without this file, every
# message you ever sent vanished the moment you closed the launcher.
CHAT_STORE_PATH = os.path.join(CUBEON_HOME, "chat_store.json")

# Pending P2P invites we haven't accepted yet, keyed by friend. Bounded because
# a friend who invites, cancels, invites again... used to add a dead room id per
# attempt, forever (the map was never pruned).
_MAX_PENDING_ROOMS = 16

# One string for every "the socket isn't up" refusal, so the mod shows the same
# sentence whichever action was attempted. This is the Friends tab's wording.
_NOT_CONNECTED = "Not connected yet. Try again in a moment."

# How long a sync room may sit idle before the janitor closes it. A room costs
# two rows in the Worker's `calls` table and nothing else, but a mod that
# crashes mid-sync would otherwise leave them there for the life of the Durable
# Object. Generous enough to survive reading a long report and then pressing
# Download.
_SYNC_IDLE_S = 300.0

# How long to wait for a friend's sealed reply before saying so. The relay is a
# WebSocket both sides already hold open, so a live friend answers in well under
# a second; this only ever fires when they closed the game or lost signal
# between the roster saying "online" and the request landing.
_SYNC_REPLY_TIMEOUT_S = 20.0

# A download that stops receiving chunks for this long is declared stalled
# rather than left spinning forever. Matches p2p.MOD_SYNC_TIMEOUT_S's intent.
_SYNC_CHUNK_TIMEOUT_S = 45.0

# Most a single sync will pull, so a friend with a 400-mod pack can't quietly
# push gigabytes through a free relay. Above this the report says to use the
# modpack tab instead.
_SYNC_MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024

# How long an identical notice is swallowed. Long enough to cover the race
# between the relay's WS reply and the local REST check for the same typo'd
# add; short enough that a deliberate repeat (say, adding the same bad name
# twice a minute apart) still tells the player both times.
_NOTICE_DEDUPE_SECONDS = 10.0

# How long the host waits for a password proof before tearing the invite down
# (joiner walked away / closed the game). The punch path's own idle timeout is
# 30s on live traffic; a human typing a password gets a bit more than that.
_GATE_TIMEOUT = 60.0

# How long a peer's advertised E2EE public key stays trusted (S15). A peer
# that rotates their key (lost identity.json, re-claimed) would otherwise get
# messages sealed to a dead key forever - encryption with a stale-but-valid
# key succeeds silently. TTL bounds the damage; reconnect invalidation covers
# the "my friend just fixed it, retry now" case.
_PUBKEY_TTL_S = 900.0


def _mod_stem(filename):
    """'sodium-fabric-0.5.11.jar' -> 'sodium-fabric'. The leading run of
    filename tokens before the first digit-led one - the mod NAME, which
    every version of it shares. A filename that starts with a digit yields
    "" ("1.20-fix" is not a stable name), so it can never claim a match.

    This is a presentation heuristic for the sync report's "different
    version" call-out; it never gates a download, so a wrong guess costs at
    most a confusing label, never a broken join."""
    base = (str(filename or "").split(".jar", 1)[0] or "").strip().lower()
    if base[:1].isdigit():
        return ""
    keep = []
    for token in base.split("-"):
        if token[:1].isdigit():
            break
        keep.append(token)
    return "-".join(keep)


def _default_save_config(cfg: dict) -> None:
    # save_config lives in launcher_core; imported lazily so this module doesn't
    # depend on main.py's import graph or create a cycle.
    import launcher_core as core
    core.save_config(cfg)


def _core():
    """launcher_core, imported on first use.

    launcher_core re-exports most of the cubeon package, so importing it at
    module scope from *inside* cubeon would invert the dependency and risk an
    import cycle. After the first call this is a sys.modules hit.
    """
    import launcher_core as core
    return core


def _wait_session_closed(session, timeout: float) -> bool:
    """True once `session` has been closed, False if it's still alive after
    `timeout` seconds.

    This reaches into `session._stop`, a private threading.Event shared by
    PunchSession/HybridSession/RelaySession. It is isolated here (rather than
    inlined in the watchdog, where it used to live) because it is the one place
    this module touches p2p.py's internals: the right fix is a public
    `wait_closed(timeout)` on those three classes, at which point only this
    helper changes.
    """
    return session._stop.wait(timeout)


class FriendsService:
    """Owns the friends client's callbacks, the P2P world state machine, and
    the local_api bridge that the in-game mod drives.

    `cfg` and `state` are the launcher's live dicts, held by reference on
    purpose: the tab re-read state["selected_version"] and state["mod_loader"]
    on every single use so that changing the Play tab mid-session was picked up
    immediately. Snapshotting either one would silently launch the wrong
    profile.
    """

    # The process-scoped instance, set by start() (see the comment there).
    # Exactly one service per process is the contract, so a class-level
    # reference is the seam other Cubeon modules use to reach the in-game
    # mod's Minecraft chat (FriendsService.notify_active).
    _active = None

    # local_api setter -> method on this service. Missing setters are skipped,
    # so this module works against both the bridge as shipped today and the
    # wider one being written alongside it.
    _LOCAL_API_BINDINGS = (
        ("set_roster_provider", "roster_payload"),
        ("set_status_provider", "status_payload"),
        ("set_invite_handler", "invite"),
        ("set_cancel_handler", "cancel"),
        ("set_add_handler", "add_friend"),
        ("set_accept_handler", "accept"),
        ("set_decline_handler", "decline"),
        ("set_rename_handler", "rename"),
        # Endpoints the in-game UI needs that the Friends tab never exposed.
        ("set_join_handler", "join"),
        ("set_retry_handler", "retry"),
        ("set_remove_handler", "remove"),
        ("set_whitelist_handler", "set_whitelisted"),
        ("set_events_provider", "events_since"),
        # Encrypted chat: POST /dm (send) and GET /chat (transcript polling).
        ("set_dm_handler", "send_chat"),
        ("set_chat_provider", "chat_payload"),
        # Profile sync: compare this machine's Minecraft against a friend's and
        # pull whatever it's missing into the global mods store.
        ("set_sync_provider", "sync_payload"),
        ("set_sync_start_handler", "sync_start"),
        ("set_sync_download_handler", "sync_download"),
        ("set_sync_close_handler", "sync_close"),
        # "Ask to join" - the other half of the Play button: instead of hosting,
        # nudge the friend to host for us.
        ("set_askjoin_handler", "ask_join"),
        # GET /players - skin/cape/presence details for every Cubeon name this
        # launcher can vouch for; the in-game Friends screen's roster reads it.
        ("set_players_provider", "players_payload"),
        # Worldgate: the host's optional LAN-world password (POST /worldgate)
        # and the joiner's proof answer (POST /joinpassword).
        ("set_worldgate_handler", "worldgate_set"),
        ("set_joinpassword_handler", "join_password"),
    )

    def __init__(self, cfg: dict, state: dict, client, *, save_config=None):
        self.cfg = cfg
        self.state = state
        self.client = client
        self._save_config = save_config or (lambda: _default_save_config(self.cfg))

        # Guards the session dict *reference* and the pending-invite map. Not
        # the contents of a session: see the module docstring.
        self._lock = threading.RLock()
        self._metadata_lock = threading.RLock()
        self._peer_metadata = {}
        self._username_lock = threading.RLock()
        self._minecraft_username = None
        # Active P2P world session, or None.
        # state: "hosting_wait_port" | "ringing_out" | "ringing_in" |
        #        "connecting" | "connected" | "launching" | "ended" | "failed"
        # net_ready/mods_ready/assets_ready: joining only happens once all
        # three are True - see _maybe_finish_join(), the roadmap Phase 2b
        # "parallel, not blocking each other" decision.
        self._session = None
        self._pending_rooms = {}   # canonical friend name -> room id
        self._invited_by = set()   # canonical names with a pending P2P invite

        # Notification log + revision counter. Separate lock: _notify is called
        # from at least six threads and must never wait on the state machine.
        self._notify_lock = threading.Lock()
        self._events = collections.deque(maxlen=_MAX_EVENTS)
        self._seq = 0
        # text -> monotonic time of the last identical notice. Dedupes the two
        # independent sources of the "no such user" answer (the relay's own
        # T_SYSTEM reply and the local REST fallback below), which can both
        # fire for the same typo'd add.
        self._notice_seen = {}
        self._revision = 0

        # Encrypted DM state. One ring per canonical friend name; each entry is
        # {"seq", "dir" ("in"|"out"), "name", "text", "ts"} with seq monotonic
        # per conversation so the mod's cursor ("after") is just an int compare.
        # Decryption happens here, on arrival - the relay only ever hands us
        # ciphertext envelopes (cubeon/e2ee.py). Guarded by its own lock so the
        # WS thread never blocks the state-machine lock.
        self._chat_lock = threading.RLock()
        self._chat = {}            # canon peer -> {"next_seq": int, "msgs": deque}
        self._chat_seeded = {}     # canon -> {"gen": int, "t": float} | "done"
        self._chat_read = {}       # canon peer -> highest seq marked seen
        self._connect_gen = 0      # bumped on every (re)connect for history reseed
        # Hydrate the rings from chat_store.json BEFORE anything can append, so
        # a restart resumes every conversation exactly where it left off. The
        # file is the only copy of your own sent messages (see CHAT_STORE_PATH).
        self._hydrate_chat_store()
        self._chat_dirty = False
        self._chat_save_timer = None
        # Plaintext of messages we've sent, waiting on the relay's echo as the
        # "it was stored" confirmation before they enter the ring. A sender can
        # never decrypt its own envelope (the shared secret needs the *peer's*
        # key, and only the peer's public half ever leaves its machine), so the
        # echo is a signal, not a source of text. Keyed by (peer canon, ts).
        self._out_pending = {}
        # This machine's E2EE identity, loaded lazily off identity.json.
        self._e2ee_priv = None
        self._e2ee_pubkey = None
        self._pubkey_published = False
        # canon peer -> (public key, cached-at monotonic), so the pubkey lookup
        # that gates every encrypted send is paid once per friend per TTL
        # window instead of on every message. Both send_chat() and the Sync
        # channel run on threads a UI is blocking on, so a repeated 4-second
        # REST round trip there reads as lag in the one place it is most
        # visible. Entries expire after _PUBKEY_TTL_S and are invalidated on
        # every reconnect: a peer that rotated their key (S15) would otherwise
        # receive messages sealed to a dead key FOREVER, because encryption
        # with a stale-but-valid key succeeds silently.
        self._peer_pubkeys = {}

        # ---- profile Sync (the mod's Sync view) -------------------------------
        # A sync is a short-lived room on the same relay the P2P handshake uses,
        # opened with call_invite(kind="sync"). It carries an E2EE-sealed profile
        # exchange and, on request, the mod jars themselves - so the relay never
        # learns which mods either side runs. Deliberately NOT a P2P session:
        # comparing profiles must work while a world session is live, and must
        # never launch or tear down a game.
        self._sync_lock = threading.RLock()
        self._syncs = {}        # canon peer -> report dict (see _sync_new)
        self._sync_rooms = {}   # room id -> canon peer

        self._started = False
        # Tracked apart from _started: FriendsClient.on() has no counterpart to
        # unregister, so a stop()/start() cycle must not subscribe twice or
        # every notification would arrive in duplicate.
        self._handlers_bound = False

    # =====================================================================
    # Lifecycle.
    # =====================================================================

    def start(self) -> None:
        """Register the client callbacks and the bridge, then start the bridge.

        Idempotent, and safe before the client has connected - nothing here
        talks to the network.
        """
        if self._started:
            return
        self._started = True
        # The process-scoped service: exactly one per process (main.py guards
        # against a second local_api server stealing the token file), so a
        # class-level reference is the clean seam for OTHER Cubeon modules
        # (the Server tab's share flow) to push a line into the in-game mod's
        # Minecraft chat without threading a service handle through every
        # constructor. Cleared on shutdown so a stale reference can't eat
        # notices meant for the next session.
        FriendsService._active = self
        self.reconcile_username()
        self._remember_roster(self.client.roster)
        self._bind_client_handlers()

        # p2p.cleanup_stale_sessions() had no caller anywhere in the launcher,
        # so ~/.cubeon_launcher/p2p_sessions accumulated a file per crashed or
        # force-quit session forever. One conservative sweep per process start
        # (it only touches metadata older than a day, through the same guarded
        # teardown path).
        try:
            removed = p2p.cleanup_stale_sessions()
            if removed:
                log.info("cleaned up %d stale P2P session(s)", removed)
        except Exception:
            log.debug("stale P2P session cleanup failed", exc_info=True)

        try:
            from cubeon import local_api
        except Exception:
            log.warning("local_api unavailable; the in-game mod can't connect",
                        exc_info=True)
            return

        # Providers BEFORE local_api.start(). main.py used to start the bridge
        # early and let the Friends tab register into it later, which left a
        # window where a mod polling /friends got a 503 from a running server.
        for setter_name, method_name in self._LOCAL_API_BINDINGS:
            setter = getattr(local_api, setter_name, None)
            if setter is None:
                log.debug("local_api has no %s; skipping", setter_name)
                continue
            try:
                setter(getattr(self, method_name))
            except Exception:
                log.warning("local_api.%s failed", setter_name, exc_info=True)

        try:
            if not local_api.start():
                log.warning("local bridge didn't start; the in-game Friends "
                            "button will be inert")
        except Exception:
            log.warning("local bridge failed to start", exc_info=True)

        # Get this machine's E2EE public key onto the server as soon as there's
        # an identity and a connection, so friends can write us encrypted DMs
        # without us having to send first. Best-effort and idempotent.
        try:
            if friends.load_identity():
                threading.Thread(target=self._publish_when_connected,
                                 daemon=True,
                                 name="cubeon-e2ee-publish").start()
        except Exception:
            log.debug("couldn't schedule the e2ee key publish", exc_info=True)

    def stop(self) -> None:
        """Stop the bridge and tear down any live session. Never raises.

        Every thread this module starts is a daemon, so there is nothing to
        join - they die with the process.
        """
        FriendsService._active = None
        # Get any not-yet-written chat ring onto disk BEFORE the process can
        # exit - the last chance to keep a just-sent message from disappearing
        # (see CHAT_STORE_PATH; sent messages have no relay-side copy).
        try:
            self.flush_chat_store()
        except Exception:
            log.debug("chat store flush on stop failed", exc_info=True)
        try:
            from cubeon import local_api
            local_api.stop()
        except Exception:
            log.debug("local bridge shutdown failed", exc_info=True)
        try:
            self._hard_teardown()
        except Exception:
            log.debug("P2P teardown on shutdown failed", exc_info=True)
        self._started = False

    def set_version(self, version: "str | None") -> None:
        """Presence: "playing 1.20.1", or None when the game stops. main.py's
        launch path calls this instead of poking the client directly, so
        everything social goes through one object."""
        try:
            self.client.set_version(version)
        except Exception:
            # Presence is never worth failing a game launch over.
            log.debug("set_version failed", exc_info=True)

    # =====================================================================
    # Notifications + change detection (what the UI used to be).
    # =====================================================================

    def _changed(self) -> None:
        """Something the mod can see may have changed. Replaces every
        render_roster()/render_p2p_banner()/page.update()/set_conn()/
        show_view() call in the old tab."""
        with self._notify_lock:
            self._revision += 1

    def revision(self) -> int:
        with self._notify_lock:
            return self._revision

    @classmethod
    def notify_active(cls, text: str, error: bool = False) -> bool:
        """Pushes a line into the in-game mod's Minecraft chat (or the status
        line while a Cubeon screen is open), without owning a service handle.

        This is how module-adjacent features - the Server tab learning the
        Minekube public address, say - reach the player in the game: the
        notice joins the same event ring the mod polls, so it renders wherever
        the mod renders notices. False when this process has no active
        service (headless tests, the service never started, or it stopped) -
        the caller carries on, chat is best-effort.

        Safe from any thread: _notify takes the ring's lock.
        """
        service = cls._active
        if service is None:
            return False
        try:
            service._notify(text, error)
        except Exception:
            log.debug("notify_active couldn't deliver %r", text, exc_info=True)
            return False
        return True

    def _notify(self, text, error: bool = False) -> None:
        """One toast, addressed to whoever is drawing the UI now.

        The same sentence delivered twice within a few seconds is shown once.
        This exists for the add-a-typo'd-name flow, where the relay's own
        "No Cubeon user named X." reply and the launcher's local REST fallback
        can both land for the same action - but it is general: two identical
        toasts that close together are noise either way.
        """
        text = str(text or "").strip()
        if not text:
            return
        now = time.monotonic()
        with self._notify_lock:
            last = self._notice_seen.get(text)
            if last is not None and now - last < _NOTICE_DEDUPE_SECONDS:
                return
            self._notice_seen[text] = now
            while len(self._notice_seen) > 64:
                self._notice_seen.pop(next(iter(self._notice_seen)))
            self._seq += 1
            self._events.append({"seq": self._seq, "text": text,
                                 "error": bool(error)})
            self._revision += 1
        log.info("friends notice%s: %s", " (error)" if error else "", text)

    def notify(self, text: str, error: bool = False) -> None:
        """Public wrapper - lets main.py surface a launcher-side notice in the
        same in-game feed."""
        self._notify(text, error=error)

    def events_since(self, since: int) -> dict:
        """Everything logged after `since`, plus the cursor to pass next time.

        A negative `since` means "first sync": the caller gets the current
        cursor and no events, because a mod that just loaded must not be
        greeted with a backlog of notifications from an hour ago.
        """
        try:
            since = int(since)
        except (TypeError, ValueError):
            since = -1
        with self._notify_lock:
            cursor = self._seq
            if since < 0:
                return {"cursor": cursor, "events": []}
            return {"cursor": cursor,
                    "events": [dict(e) for e in self._events
                               if e["seq"] > since]}

    # =====================================================================
    # Session bookkeeping.
    # =====================================================================

    def _session_get(self):
        with self._lock:
            return self._session

    def _session_set(self, session) -> None:
        with self._lock:
            self._session = session

    def _remember_pending(self, conv: str, room: str) -> None:
        """Record an incoming P2P invite and light up that friend's Join."""
        with self._lock:
            self._pending_rooms[conv] = room
            self._invited_by.add(conv)
            # Drop the oldest if a burst of invites piles up - dict preserves
            # insertion order, so the first key is the stalest.
            while len(self._pending_rooms) > _MAX_PENDING_ROOMS:
                stale = next(iter(self._pending_rooms))
                del self._pending_rooms[stale]
                self._invited_by.discard(stale)

    def _forget_pending(self, *, conv: str = None, room: str = None) -> None:
        """Forget an invite that can no longer be joined (declined, ended, or
        consumed). Both the room id and the Join flag go, so the mod never
        offers a Join that resolves to a dead room."""
        with self._lock:
            for key, value in list(self._pending_rooms.items()):
                if (conv is not None and key == conv) or \
                        (room is not None and value == room):
                    del self._pending_rooms[key]
                    self._invited_by.discard(key)

    def _pending_room(self, conv: str):
        with self._lock:
            return self._pending_rooms.get(conv)

    def _hard_teardown(self) -> None:
        """Shutdown-only teardown. _end_p2p() normally lets on_call_end do the
        cleanup so there's exactly one path, but at process exit that callback
        will never arrive - so do all of it here, best-effort."""
        with self._lock:
            p, self._session = self._session, None
            self._pending_rooms.clear()
            self._invited_by.clear()
        worldgate.clear()
        if not p:
            return
        room = p.get("room")
        if room:
            try:
                self.client.call_end(room)
            except Exception:
                pass
        if p.get("punch"):
            try:
                p["punch"].close()
            except Exception:
                pass
        if room and not p.get("is_host"):
            try:
                p2p.teardown(room)
            except Exception:
                pass
        self._changed()

    def _my_name(self) -> str:
        ident = friends.load_identity()
        return ident["name"] if ident else ""

    def _my_uid(self) -> str:
        """This machine's 8-digit Cubeon ID, or "" until the server assigns
        one. Read off the identity file rather than the client, so it is the
        same value the Chat surface shows in the launcher and the mod."""
        ident = friends.load_identity()
        if not ident:
            return ""
        return friends.canonical_uid(ident.get("uid")) or ""

    def _effective_username(self) -> str:
        try:
            from cubeon import watchdog
            return friends.minecraft_username(
                watchdog.effective_username(self.cfg.get("username")))
        except Exception:
            return friends.minecraft_username(self.cfg.get("username"))

    def reconcile_username(self) -> str:
        with self._username_lock:
            username = self._effective_username()
            if username != self._minecraft_username:
                self._minecraft_username = username
                self._changed()
            try:
                self.client.set_minecraft_username(username)
            except Exception:
                log.debug("username publication failed", exc_info=True)
            return username

    @classmethod
    def reconcile_username_active(cls) -> str:
        try:
            return cls._active.reconcile_username() if cls._active else ""
        except Exception:
            log.debug("active username reconciliation failed", exc_info=True)
            return ""

    def _remember_metadata(self, row, handle=None, fill_missing_only=False) -> None:
        if not isinstance(row, dict):
            return
        name = handle if isinstance(handle, str) else row.get("name")
        canon = friends.canonical_name(name) if isinstance(name, str) else None
        if not canon:
            return
        with self._metadata_lock:
            saved = self._peer_metadata.setdefault(canon, {"name": name})
            uid = friends.canonical_uid(row.get("uid"))
            username = friends.minecraft_username(row.get("minecraft_username"))
            if fill_missing_only:
                if uid and not saved.get("uid"):
                    saved["uid"] = uid
                if username and not saved.get("minecraft_username"):
                    saved["minecraft_username"] = username
            else:
                if uid:
                    saved["uid"] = uid
                if username:
                    saved["minecraft_username"] = username

    def _remember_event(self, payload) -> None:
        if not isinstance(payload, dict):
            return
        rows = [(k, v) for k, v in payload.items()
                if isinstance(v, dict) and not isinstance(v.get("name"), str)
                and ("uid" in v or "minecraft_username" in v)]
        if rows and not any(k in payload for k in ("name", "from", "to", "peer")):
            for handle, row in rows:
                self._remember_metadata(row, handle)
            self._changed()
            return
        self._remember_roster(self.client.roster)
        # "name" prefix: metadata events and friend_added carry authoritative
        # uid/username for a single handle - overwrite existing (not fill-missing).
        for prefix in ("name",):
            handle = payload.get(prefix)
            if isinstance(handle, str):
                self._remember_metadata({
                    "uid": payload.get("uid"),
                    "minecraft_username": payload.get("minecraft_username"),
                }, handle)
        for prefix in ("from", "to", "peer"):
            handle = payload.get(prefix)
            if isinstance(handle, dict):
                self._remember_metadata(handle, fill_missing_only=True)
            elif isinstance(handle, str):
                self._remember_metadata({
                    "uid": payload.get(prefix + "_uid"),
                    "minecraft_username": payload.get(prefix + "_minecraft_username"),
                }, handle, fill_missing_only=True)
        self._changed()

    def _bind_client_handlers(self) -> None:
        """Bind every relay event exactly once. The single binding contract for
        start() and any test/consumer that wants the handler set without the
        bridge or reconcile threads."""
        if self._handlers_bound:
            return
        self._handlers_bound = True
        c = self.client
        for event, fn in (("state", self._on_state),
                          ("metadata", self._remember_event),
                          ("hello_ok", self._remember_event),
                          ("roster", self._on_roster),
                          ("presence", self._on_presence),
                          ("request", self._on_request),
                          ("friend_added", self._on_friend_added),
                          ("friend_removed", self._on_friend_removed),
                          ("system", self._on_system),
                          ("error", self._on_error),
                          ("call_invite", self._on_call_invite),
                          ("call_accept", self._on_call_accept),
                          ("call_decline", self._on_call_decline),
                          ("call_end", self._on_call_end),
                          ("signal", self._on_signal),
                          ("dm", self._on_dm),
                          ("history", self._on_history)):
            c.on(event, fn)

    def _remember_roster(self, roster) -> None:
        """Learn identity fields from a roster view (S3+S4).

        Two trust tiers. The client's own `peer_metadata` cache is
        authoritative: FriendsClient merges every T_METADATA event into it
        BEFORE dispatching, so at handler time it is the freshest known
        state, and it is mirrored unconditionally. Raw friend/request detail
        rows are only a legacy fallback: they gap-fill handles and fields
        the service doesn't know yet, and can never overwrite a value a
        live event already delivered - so a reordered or lagging snapshot
        can't resurrect a stale username."""
        if not isinstance(roster, dict):
            return
        cached = roster.get("peer_metadata")
        if not isinstance(cached, dict):
            cached = roster.get("metadata")
        authoritative = {}
        if isinstance(cached, dict):
            for handle, row in cached.items():
                if isinstance(handle, str) and isinstance(row, dict):
                    authoritative[handle] = row
        known_canons = {friends.canonical_name(h) for h in authoritative}
        gapfill = {}
        for key in ("friends", "requests_in_details", "requests_out_details"):
            values = roster.get(key)
            if not isinstance(values, list):
                continue
            for row in values:
                if not isinstance(row, dict):
                    continue
                handle = row.get("name")
                if not isinstance(handle, str):
                    continue
                canon = friends.canonical_name(handle)
                if not canon or canon in known_canons:
                    continue
                if row.get("uid") or row.get("minecraft_username"):
                    gapfill[handle] = row
        with self._metadata_lock:
            for handle, row in authoritative.items():
                self._remember_metadata(row, handle)
            for handle, row in gapfill.items():
                canon = friends.canonical_name(handle)
                known = self._peer_metadata.get(canon, {})
                uid = friends.canonical_uid(row.get("uid"))
                username = friends.minecraft_username(row.get("minecraft_username"))
                if ((uid and not known.get("uid"))
                        or (username and not known.get("minecraft_username"))):
                    self._remember_metadata(row, handle)

    def peer_metadata(self, handle) -> dict:
        name = handle if isinstance(handle, str) else ""
        canon = friends.canonical_name(name) or ""
        if not canon and not isinstance(handle, dict):
            data = {}
        else:
            self._remember_roster(self.client.roster)
            with self._metadata_lock:
                data = dict(self._peer_metadata.get(canon, {}))
        if isinstance(handle, dict):
            uid = friends.canonical_uid(handle.get("uid"))
            username = friends.minecraft_username(handle.get("minecraft_username"))
        else:
            uid = friends.canonical_uid(data.get("uid")) or ""
            username = friends.minecraft_username(data.get("minecraft_username"))
        if canon and canon == friends.canonical_name(self._my_name()):
            uid = self._my_uid()
            username = self._effective_username()
        return {"name": name, "uid": uid, "minecraft_username": username,
                "display_name": username or (f"Cubeon ID {uid}" if uid else "Player")}

    def peer_label(self, handle) -> str:
        data = self.peer_metadata(handle)
        label = data["display_name"]
        if data["minecraft_username"] and data["uid"]:
            label += f" (Cubeon ID {data['uid']})"
        return label

    def _peer_fields(self, handle) -> dict:
        data = self.peer_metadata(handle)
        return {"peer_uid": data["uid"],
                "peer_minecraft_username": data["minecraft_username"],
                "peer_display_name": data["display_name"]}

    @staticmethod
    def _ok() -> dict:
        return {"ok": True, "error": ""}

    @staticmethod
    def _err(message) -> dict:
        return {"ok": False, "error": str(message or "")}

    # =====================================================================
    # Read models - the two GET endpoints.
    # =====================================================================

    def roster_payload(self) -> dict:
        """GET /friends. Presence is sent raw (online/version/status): the mod
        renders its own presence line, so nothing pre-rendered goes over the
        bridge."""
        roster = self.client.roster or {}
        self._remember_roster(roster)
        you = friends.current_name() or ""
        you_metadata = self.peer_metadata(you)
        requests = {key: [r for r in (roster.get(key) or [])
                          if isinstance(r, str) and r]
                    for key in ("requests_in", "requests_out")}
        version_id = self.state.get("selected_version")
        with self._lock:
            invited = set(self._invited_by)

        # Online first, then alphabetical - the order the roster was always
        # shown in, kept here so every client agrees on it for free.
        entries = [f for f in (roster.get("friends") or [])
                   if isinstance(f, dict) and f.get("name")]
        entries.sort(key=lambda f: (not f.get("online"), f["name"].lower()))

        out = []
        whitelist = self._whitelist_names(version_id)
        for f in entries:
            name = f["name"]
            conv = friends.canonical_name(name) or name.lower()
            with self._chat_lock:
                room = self._chat.get(conv)
                msgs = list(room["msgs"]) if room else []
                read = self._chat_read.get(conv, 0)
            last = msgs[-1] if msgs else None
            meta = self.peer_metadata(name)
            out.append({
                **meta,
                "online": bool(f.get("online")),
                "version": f.get("version") or "",
                "status": f.get("status") or "",
                "invited": conv in invited,
                # The server whitelist is keyed by MINECRAFT username, never
                # by the internal relay handle: a handle in whitelist.json
                # would whitelist nobody (S12).
                "whitelisted": (meta["minecraft_username"].strip().lower()
                                in whitelist if meta["minecraft_username"]
                                else False),
                "last_text": (last.get("text") or "") if last else "",
                "last_ts": int(last.get("ts") or 0) if last else 0,
                "last_dir": (last.get("dir") or "") if last else "",
                "unread": sum(1 for m in msgs
                              if m.get("dir") == "in" and m.get("seq", 0) > read),
            })
        return {
            "you": you,
            "you_uid": self._my_uid(),
            "you_minecraft_username": you_metadata["minecraft_username"],
            "you_display_name": you_metadata["display_name"],
            "connected": bool(self.client.is_connected),
            "available": bool(self.client.is_available),
            "friends": out,
            **requests,
            "requests_in_details": [self.peer_metadata(r) for r in requests["requests_in"]],
            "requests_out_details": [self.peer_metadata(r) for r in requests["requests_out"]],
            # Freshness fingerprint of the jar this launcher WOULD install.
            # The running mod hashes its own jar and compares; a mismatch
            # means the game is running an old mod and needs a relaunch.
            "mod_stamp": _mod_stamp(version_id),
        }

    def players_payload(self) -> dict:
        """GET /players. What the in-game menu knows about Cubeon players.

        Every name this launcher can vouch for - this machine's own account
        plus the whole roster - with whatever skin/cape detail is on local
        disk. Skins and capes are CSL-keyed off the Minecraft username, so the
        local account is the only one whose files this machine can see: a
        friend's skin lives on THEIR launcher, and the mod renders "default"
        rather than inventing one.

        Polled about once a second while a menu is open, so: no network calls,
        no locks beyond the roster read, and any failure degrades to an empty
        list - the mod treats fewer rows as "nothing known", never an error.
        """
        roster = self.client.roster or {}
        you = friends.current_name() or ""
        version_id = self.state.get("selected_version") or ""

        entries = [f for f in (roster.get("friends") or [])
                   if isinstance(f, dict) and f.get("name")]
        entries.sort(key=lambda f: (not f.get("online"), f["name"].lower()))

        players = []
        if you:
            players.append({
                **self.peer_metadata(you),
                "online": True,
                "skin": _local_skin_name(self.cfg),
                "cape": _local_cape_name(self.cfg),
                "version": version_id,
                "status": "you",
            })
        for f in entries:
            if you and f["name"].strip().lower() == you.lower():
                continue
            players.append({
                **self.peer_metadata(f["name"]),
                "online": bool(f.get("online")),
                # A friend's skin/cape lives on their launcher; the shared
                # backend serves the pixels to the game itself (CSL), so the
                # bridge only carries what it can prove. The mod renders
                # "default"/"none" for these.
                "skin": "",
                "cape": "",
                "version": f.get("version") or "",
                "status": f.get("status") or "",
            })
        return {"players": players}

    def _whitelist_names(self, version_id) -> set:
        """The whitelist as a lowercase set, read ONCE per payload.

        The friend row used to ask core.is_whitelisted(version, name) per friend,
        which re-read and re-parsed whitelist.json for each one. That was fine
        when a render happened because someone clicked; the mod polls this
        endpoint about once a second, which would turn a 30-friend roster into 30
        file reads a second forever.

        Same broad guard the friend row had: no server installed, an unreadable
        whitelist.json or a half-written server dir must render a roster, not
        raise.
        """
        if not version_id:
            return set()
        try:
            return {str(n).strip().lower() for n in _core().get_whitelist(version_id)}
        except Exception:
            return set()

    @staticmethod
    def _quality_line(p: dict) -> str:
        """The one-line transport summary the banner showed under "Connected to
        X's world" - moved verbatim from render_p2p_banner()."""
        metrics = p.get("metrics") or {}
        rtt = metrics.get("rtt_ms")
        mode = metrics.get("mode")
        if p.get("minekube_active"):
            return (f"Via Minekube - {p.get('minekube_address') or 'public server'} "
                    f"(P2P fell back)")
        if mode == "relay":
            return ("Relayed via Cubeon servers (higher ping - trying to open a "
                    "direct path...)")
        if mode == "handover":
            return "Direct path opening - switching over..."
        return (f"Direct • {rtt:.0f} ms" if isinstance(rtt, (int, float))
                else "Direct P2P")

    def status_payload(self) -> dict:
        """GET /status. {} when there's no session at all."""
        p = self._session_get()
        if not p:
            return {}
        state_ = p.get("state") or ""
        return {
            "state": state_,
            "peer": p.get("peer") or "",
            **self._peer_fields(p.get("peer")),
            "error": p.get("error"),
            "is_host": bool(p.get("is_host")),
            # Only meaningful once a transport exists; the banner likewise only
            # drew it in the connected state, so don't claim "Direct P2P" while
            # still handshaking.
            "quality": (self._quality_line(p)
                        if state_ in ("connected", "launching") else ""),
            # Exactly when the banner offered a Retry button.
            "can_retry": bool(state_ == "failed" and not p.get("is_host")
                              and p.get("offer") and not p.get("net_ready")),
        }

    # =====================================================================
    # Encrypted chat. DMs ride the existing relay, but only as ciphertext
    # envelopes (cubeon/e2ee.py); plaintext never leaves this process. The
    # relay stays the dumb pipe it always was - it just stores and echoes an
    # opaque JSON body it can never read.
    # =====================================================================

    def _ensure_e2ee(self) -> "tuple[bytes, str] | None":
        """This machine's (private key, public key b64), loading or creating
        the key off the identity file. None when there's no identity to hang a
        key on yet. Cached after the first load so a rename (which rewrites
        identity.json but preserves e2ee_sk) keeps the same key."""
        if self._e2ee_priv is not None:
            return self._e2ee_priv, self._e2ee_pubkey
        path = getattr(friends, "IDENTITY_PATH", None)
        if not path or not os.path.isfile(path):
            return None
        try:
            priv = e2ee.load_or_create_key(path)
            self._e2ee_priv = priv
            self._e2ee_pubkey = e2ee.public_key_b64(priv)
            return self._e2ee_priv, self._e2ee_pubkey
        except Exception:
            log.warning("couldn't load the e2ee key", exc_info=True)
            return None

    def _ensure_pubkey_published(self) -> bool:
        """Publishes this machine's E2EE public key under its claimed name so
        friends can write to it. Idempotent for this process; a failure is not
        fatal (the next send retries) but is worth one debug line."""
        if self._pubkey_published:
            return True
        keypair = self._ensure_e2ee()
        if not keypair:
            return False
        try:
            pubber = getattr(self.client, "publish_pubkey", None)
            result = (pubber(keypair[1]) if pubber is not None
                      else friends.publish_pubkey(keypair[1]))
        except Exception as ex:
            log.debug("pubkey publish failed: %s", ex)
            return False
        if (result or {}).get("ok"):
            self._pubkey_published = True
            return True
        return False

    def _publish_when_connected(self) -> None:
        """Waits (briefly) for the socket, then publishes the E2EE key. Run on
        a daemon thread from start() and after a rename."""
        for _ in range(40):
            if self.client.is_connected:
                break
            if not self._started:
                return
            time.sleep(0.5)
        if self.client.is_connected:
            self._ensure_pubkey_published()

    def _chat_room(self, canon: str) -> dict:
        with self._chat_lock:
            return self._chat.setdefault(
                canon, {"next_seq": 1,
                        "msgs": collections.deque(maxlen=_MAX_CHAT)})

    def _chat_append(self, canon: str, direction: str, name: str,
                     text: str, ts, mid: str = "", envelope: str = "") -> bool:
        """One decrypted message into the peer's ring, with the next seq for
        that conversation. seq is per-conversation and monotonic for the life
        of the process, so the mod's poll cursor is a plain int compare.

        Returns True if appended, False if deduplicated (already present).
        Deduplication uses the relay's message id (mid) when available,
        otherwise a fingerprint of the sealed envelope - NEVER the plaintext,
        which may legitimately repeat ("hello again" twice must not collapse).
        """
        with self._chat_lock:
            room = self._chat_room(canon)
            # Dedupe under the same lock as append: race-free.
            if mid:
                for x in room["msgs"]:
                    if x.get("id") == mid:
                        return False
            elif envelope:
                # Fingerprint the sealed envelope (ciphertext), not the plaintext.
                env_fp = envelope
                for x in room["msgs"]:
                    if x.get("envelope") == env_fp:
                        return False
            room["msgs"].append({
                "seq": room["next_seq"], "dir": direction,
                "name": name, "text": text, "ts": int(ts or 0),
                **({"id": mid} if mid else {}),
                **({"envelope": envelope} if envelope else {})})
            room["next_seq"] += 1
        # Persist before returning: an append that never reached the file is a
        # message that vanishes on the next restart (the exact bug this fixes).
        self._schedule_chat_save()
        return True

    # -------------------------------------------------------------------
    # chat_store.json - the ring's disk copy (the disappearing-messages fix)
    # -------------------------------------------------------------------

    def _hydrate_chat_store(self) -> None:
        """Load the persisted rings into memory. Never raises: a missing or
        corrupt file just means the rings start empty (still the old behavior)."""
        try:
            with open(CHAT_STORE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        for canon, saved in (data.get("peers") or {}).items():
            if not isinstance(canon, str) or not isinstance(saved, dict):
                continue
            msgs = saved.get("msgs")
            if not isinstance(msgs, list) or not msgs:
                continue
            room = self._chat_room(canon)
            seen = set()

            def _key_of(entry):
                """Dedupe key: relay id, else sealed-envelope fingerprint,
                else the plaintext triple."""
                return (entry.get("id") or entry.get("envelope")
                        or (entry.get("dir") or "in", entry.get("text") or "",
                            entry.get("ts") or 0))

            # Seed from what the room already holds: hydrate() runs from
            # __init__ AND may be called again explicitly - without this the
            # second pass re-appended every line (an idempotency bug wearing
            # the reopen-dupe's clothes).
            for entry in list(room["msgs"]):
                seen.add(_key_of(entry))
            for m in msgs[-_MAX_CHAT:]:
                if not (isinstance(m, dict) and m.get("text")):
                    continue
                seq = m.get("seq")
                if not isinstance(seq, int):
                    seq = room["next_seq"]
                room["next_seq"] = max(room["next_seq"], seq + 1)
                mid = m.get("id") or ""
                env = m.get("envelope") or ""
                # Keeping the id/envelope at all is the fix for the reopen
                # bug: they used to be DROPPED on load, so the next history
                # backfill couldn't match the rows it replayed and every
                # restart appended the last messages all over again
                # ("close Cubeon, reopen, chat is duped - forever").
                key = mid or env or (m.get("dir") or "in", m["text"],
                                     m.get("ts") or 0)
                if key in seen:
                    continue  # already in the ring (or an old store's dupe)
                seen.add(key)
                room["msgs"].append({
                    "seq": seq,
                    "dir": m.get("dir") or "in",
                    "name": m.get("name") or canon,
                    "text": m["text"],
                    "ts": int(m.get("ts") or 0),
                    **({"id": mid} if mid else {}),
                    **({"envelope": env} if env else {})})
            read = saved.get("read")
            if isinstance(read, int) and read > 0:
                self._chat_read[canon] = max(
                    self._chat_read.get(canon, 0), read)

    def _schedule_chat_save(self) -> None:
        """Mark the store dirty and write it after a short quiet period, so a
        burst of messages (a fetched history page, a paste) writes once. The
        timer is replaced rather than joined: the file write is small and the
        next burst supersedes it."""
        self._chat_dirty = True
        timer = self._chat_save_timer
        if timer is not None:
            timer.cancel()
        timer = threading.Timer(1.0, self._write_chat_store)
        timer.daemon = True
        self._chat_save_timer = timer
        timer.start()

    def _write_chat_store(self) -> None:
        """Write every ring (bounded to its last _MAX_CHAT messages) to
        chat_store.json. Atomic-replace: write the sibling, then rename, so a
        crash mid-write can't corrupt the one copy of your sent messages.
        Never raises: losing a save must not kill whatever thread got here."""
        try:
            with self._chat_lock:
                peers = {}
                for canon, room in self._chat.items():
                    peers[canon] = {
                        "next_seq": room["next_seq"],
                        "read": self._chat_read.get(canon, 0),
                        "msgs": list(room["msgs"])[-_MAX_CHAT:]}
            tmp = CHAT_STORE_PATH + ".tmp"
            os.makedirs(CUBEON_HOME, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"peers": peers}, f)
            os.replace(tmp, CHAT_STORE_PATH)
            self._chat_dirty = False
        except Exception:
            log.debug("chat_store save failed", exc_info=True)

    def flush_chat_store(self) -> None:
        """Write any pending change now (the stop path). Cancel the debounce
        timer first so it can't fire again after the write."""
        timer = self._chat_save_timer
        if timer is not None:
            timer.cancel()
            self._chat_save_timer = None
        if self._chat_dirty:
            self._write_chat_store()

    def _on_dm(self, p) -> None:
        """A DM frame arrived over the socket - either from a friend, or the
        server's echo of one we sent. The body is an opaque E2EE envelope.

        Inbound: decrypt it here and file the plaintext in the peer's ring, so
        GET /chat only ever serves decrypted text and the relay only ever held
        ciphertext.

        Our own echo: a sender cannot decrypt its own envelope - the shared
        secret is derived from the *recipient's* public key, which only the
        recipient owns - so the echo is used purely as the relay's "stored"
        confirmation, which is when the plaintext kept by send_chat() enters
        the ring. Never raises: this runs on the socket thread."""
        self._remember_event(p)
        try:
            raw = p.get("text")
            if not isinstance(raw, str) or not raw:
                return
            envelope = json.loads(raw)
            mine = self._my_name() or ""
            if not mine:
                return
            sender = str(p.get("from") or "")
            recipient = str(p.get("to") or "")
            mine_c = friends.canonical_name(mine) or mine.lower()
            if sender and (friends.canonical_name(sender) == mine_c
                           or sender.lower() == mine_c):
                self._file_own_echo(envelope, recipient)
                return
            keypair = self._ensure_e2ee()
            if not keypair:
                return
            plain = e2ee.decrypt_dm(keypair[0], mine, envelope)
        except Exception:
            log.debug("dropping an undecryptable dm", exc_info=True)
            return
        canon = friends.canonical_name(sender) or sender.lower()
        if not canon or not sender:
            return
        ts = envelope.get("ts") or (int(p.get("ts") or 0) * 1000)
        mid = str(p.get("id") or "")
        env_str = str(p.get("text") or "")
        self._chat_append(canon, "in", sender, plain, ts, mid=mid, envelope=env_str)
        # A message that arrived on its own should be visible even when the
        # mod isn't on this conversation - the screen's status line is fed
        # from this events ring. Our own echo is already the Send feedback.
        self._notify(f"New message from {self.peer_label(sender)}.")
        self._changed()

    def _file_own_echo(self, envelope: dict, recipient: str) -> None:
        """The relay confirmed it stored a message we sent. File the plaintext
        we remembered in send_chat() (keyed by peer + envelope ts) as an
        outbound line - only once, only after the echo proves it landed."""
        canon = friends.canonical_name(recipient) or (recipient or "").lower()
        if not canon:
            return
        mine = self._my_name() or ""
        key = (canon, envelope.get("ts"))
        with self._chat_lock:
            queue = self._out_pending.get(key)
            if not queue:
                return   # nothing remembered (sent before this process, or replay)
            plain = queue.pop(0)["text"]
            if not queue:
                del self._out_pending[key]
        ts = envelope.get("ts") or int(time.time() * 1000)
        mid = str(envelope.get("id") or "")
        env_str = json.dumps(envelope, separators=(",", ":"))
        self._chat_append(canon, "out", mine, plain, ts, mid=mid, envelope=env_str)
        self._changed()

    def _on_history(self, p) -> None:
        """Backfill a freshly opened conversation from the relay's stored
        (ciphertext) history. Triggered by chat_payload() when a ring is empty;
        the reply carries the relay's recent messages, each still an envelope
        to decrypt before filing.

        Only the *peer's* messages can be opened here: stored messages from
        our own send path are sealed to the recipient's key (a sender can't
        decrypt its own envelope), so those decrypt to nothing and are skipped -
        they reach this ring through the live echo instead."""
        peer = p.get("peer")
        if not isinstance(peer, str) or not peer:
            return
        canon = friends.canonical_name(peer) or peer.lower()
        mine = self._my_name() or ""
        keypair = self._ensure_e2ee()
        if not mine or not keypair:
            return
        added = 0
        for m in (p.get("messages") or []):
            if not isinstance(m, dict):
                continue
            raw = m.get("text")
            if not isinstance(raw, str) or not raw:
                continue
            try:
                envelope = json.loads(raw)
                plain = e2ee.decrypt_dm(keypair[0], mine, envelope)
            except Exception:
                continue
            from_name = str(m.get("from") or peer)
            ts = envelope.get("ts") or (int(m.get("ts") or 0) * 1000)
            mid = str(m.get("id") or "")
            # Atomic dedupe+append under _chat_lock (inside _chat_append).
            # Uses relay's message id when present, else envelope fingerprint.
            if self._chat_append(canon, "in", from_name, plain, ts, mid=mid, envelope=raw):
                added += 1
        if added:
            self._changed()
        # Mark this conversation as successfully seeded (relay replied, even if
        # it had no history). This prevents re-requesting on every poll.
        with self._chat_lock:
            self._chat_seeded[canon] = "done"

    def _publish_async(self) -> None:
        """Fire-and-forget version of _ensure_pubkey_published().

        The blocking one is a REST POST on friends.TIMEOUT's budget, and
        send_chat()/the sync channel both run on a thread the in-game mod is
        waiting on. Publishing is only ever a courtesy to the *friend* (it lets
        them write to us), so it must never be on the critical path of our own
        send."""
        if self._pubkey_published:
            return
        threading.Thread(target=self._ensure_pubkey_published, daemon=True,
                         name="cubeon-pubkey-publish").start()

    def _peer_pubkey(self, name: str) -> dict:
        """A friend's advertised E2EE public key, cached per TTL window.

        Returns {"ok", "pubkey"} on success or {"ok": False, "error"} with a
        finished sentence. Capped at friends.FAST_TIMEOUT because every caller
        is inside an action the mod is blocking on - a friend whose key we
        already hold costs nothing at all. Entries expire after
        _PUBKEY_TTL_S and drop on reconnect (see _on_state), so a rotated key
        is re-fetched instead of silently sealing to a dead one (S15)."""
        canon = friends.canonical_name(name) or (name or "").strip().lower()
        if not canon:
            return {"ok": False, "error": "That doesn't look like a Cubeon name."}
        cached = self._peer_pubkeys.get(canon)
        if cached:
            pubkey, cached_at = cached
            if time.monotonic() - cached_at <= _PUBKEY_TTL_S:
                return {"ok": True, "pubkey": pubkey}
        try:
            lookup = self.client.fetch_pubkey(name, timeout=friends.FAST_TIMEOUT)
        except TypeError:
            # An older FriendsClient without the timeout knob. Still works, just
            # on the longer budget.
            try:
                lookup = self.client.fetch_pubkey(name)
            except Exception as ex:
                log.debug("pubkey lookup failed: %s", ex)
                return {"ok": False,
                        "error": "Couldn't reach the Cubeon friends server."}
        except Exception as ex:
            log.debug("pubkey lookup failed: %s", ex)
            return {"ok": False, "error": "Couldn't reach the Cubeon friends server."}
        lookup = lookup or {}
        if not lookup.get("ok"):
            return {"ok": False, "error": "Couldn't reach the Cubeon friends server."}
        if not lookup.get("exists"):
            return {"ok": False, "error": "That Cubeon player couldn't be found."}
        self._remember_metadata(lookup, name)
        pubkey = lookup.get("pubkey") or ""
        if not pubkey:
            return {"ok": False,
                    "error": (f"{self.peer_label(name)} hasn't set up encrypted chat yet - ask "
                              f"them to open their friends list once.")}
        self._peer_pubkeys[canon] = (pubkey, time.monotonic())
        return {"ok": True, "pubkey": pubkey}

    def send_chat(self, to: str, text: str) -> dict:
        """POST /dm: encrypt `text` for the friend and hand the envelope to
        the relay. The relay stores/forwards only ciphertext - and, crucially,
        only the recipient can ever decrypt it (a sender's shared secret needs
        the peer's key, which never leaves the peer). So the outbound line
        enters the ring when the relay's *echo* confirms the message was
        stored, not here: the transcript never shows a message that didn't
        actually land."""
        to = (to or "").strip()
        text = (text or "").strip()
        if not to:
            return self._err("Pick a friend to message.")
        if not text:
            return self._err("Type a message first.")
        if not self.client.is_connected:
            return self._err(_NOT_CONNECTED)
        mine = self._my_name() or ""
        keypair = self._ensure_e2ee()
        if not mine or not keypair:
            return self._err("Claim a Cubeon name before messaging.")
        # Best-effort and off this thread so the friend can reply; our own send
        # doesn't depend on it.
        self._publish_async()
        lookup = self._peer_pubkey(to)
        if not lookup.get("ok"):
            return self._err(lookup.get("error"))
        pubkey = lookup["pubkey"]
        try:
            envelope = e2ee.encrypt_dm(keypair[0], pubkey, mine, to, text)
        except Exception:
            log.warning("couldn't encrypt the message", exc_info=True)
            return self._err("Couldn't encrypt that message.")
        serialized = json.dumps(envelope)
        if len(serialized) > friends.MAX_DM_ENVELOPE_CHARS:
            return self._err("Message too long to send. Try a shorter one.")
        # Remember the plaintext for _file_own_echo(), which fires when the
        # relay's echo proves the message landed. Bounded: the echo for a
        # message the relay accepted should arrive in the same second.
        canon = friends.canonical_name(to) or to.lower()
        key = (canon, envelope["ts"])
        pending = {"text": text}
        with self._chat_lock:
            self._out_pending.setdefault(key, []).append(pending)
            while len(self._out_pending) > 64:
                self._out_pending.pop(next(iter(self._out_pending)))
        try:
            sent = self.client.send_dm(to, serialized)
        except Exception:
            log.debug("couldn't send the message", exc_info=True)
            sent = False
        if not sent:
            with self._chat_lock:
                queue = self._out_pending.get(key)
                if queue:
                    queue[:] = [entry for entry in queue if entry is not pending]
                    if not queue:
                        del self._out_pending[key]
            return self._err(_NOT_CONNECTED)
        self._changed()
        return self._ok()

    def chat_payload(self, friend: str, after) -> dict:
        """GET /chat. friend=<name>, after=-1 means "most recent page" (and the
        first time a conversation is opened — or the first access after a
        reconnect — asks the relay for its stored history so offline messages
        backfill even into a conversation that already has local lines);
        after>=0 returns everything with seq > after, ascending."""
        peer = (friend or "").strip()
        canon = friends.canonical_name(peer) or peer.lower()
        you = self._my_name() or ""
        with self._chat_lock:
            room = self._chat.get(canon)
            msgs = list(room["msgs"]) if room else []
            seeded = self._chat_seeded.get(canon)
            connected = bool(getattr(self.client, "is_connected", False))
            now = time.monotonic()
            # Determine if we need to (re)request history:
            # - never requested (None)
            # - marked for retry ("retry")
            # - previous attempt timed out (dict with gen mismatch or timeout)
            # - reconnect bumped _connect_gen (gen mismatch)
            need_seed = False
            if canon and connected:
                if seeded is None or seeded == "retry":
                    need_seed = True
                elif isinstance(seeded, dict):
                    gen = seeded.get("gen", 0)
                    last_req = seeded.get("t", 0)
                    attempts = seeded.get("attempts", 0)
                    if gen != self._connect_gen:
                        need_seed = True
                    elif now - last_req > _HISTORY_REQ_TIMEOUT:
                        # Request timed out - mark for retry with backoff
                        need_seed = True
                    # else: request in flight, wait for reply
            try:
                after = int(after) if after is not None else -1
            except (TypeError, ValueError):
                after = -1
        if after >= 0:
            # Polling for new messages: if we haven't successfully seeded yet,
            # trigger a request so gaps get filled.
            if need_seed:
                with self._chat_lock:
                    self._chat_seeded[canon] = {
                        "gen": self._connect_gen, "t": time.monotonic(), "attempts": 1}
                if peer:
                    self.client.request_history(peer=peer)
            return {"friend": peer, "you": you,
                    "messages": [m for m in msgs if m["seq"] > after]}
        if need_seed:
            with self._chat_lock:
                self._chat_seeded[canon] = {
                    "gen": self._connect_gen, "t": time.monotonic(), "attempts": 1}
            if peer:
                self.client.request_history(peer=peer)
        return {"friend": peer, "you": you,
                "messages": msgs[-_CHAT_PAGE:]}

    def mark_read(self, friend: str) -> dict:
        """Mark a conversation as seen up to its newest message.

        The launcher's Chat tab calls this while a conversation is open (each
        poll and on select), which is what clears the roster's unread badge.
        Idempotent and monotonic: the marker only ever moves forward, so a
        stale poll can't resurrect an already-read badge."""
        peer = (friend or "").strip()
        canon = friends.canonical_name(peer) or peer.lower()
        if not canon:
            return self._err("Pick a friend first.")
        with self._chat_lock:
            room = self._chat.get(canon)
            top = (room["next_seq"] - 1) if room else 0
            if top > self._chat_read.get(canon, 0):
                self._chat_read[canon] = top
                changed = True
            else:
                changed = False
        if changed:
            self._schedule_chat_save()
            self._changed()
        return self._ok()

    # =====================================================================
    # Profile Sync (the mod's Sync view). Compares this machine's Minecraft
    # against a friend's and, on request, pulls the jars it's missing.
    #
    # Rides the same relay as the P2P handshake - call_invite(kind="sync")
    # opens a room, signal() carries the traffic - but every payload is sealed
    # with the same X25519+AES-GCM envelope chat uses, so the relay learns only
    # that two friends exchanged some bytes, never which mods either one runs.
    #
    # Deliberately NOT a P2P session: comparing profiles has to work while a
    # world session is live, and must never launch or tear down a game.
    # =====================================================================

    def _sync_profile(self) -> dict:
        """This machine's Play profile in the shape the sync wire uses.

        Re-reads `state` on every call rather than snapshotting, for the reason
        in the class docstring: the player can change the Play tab between
        opening the Sync view and pressing Download.
        """
        core = _core()
        version_id = self.state.get("selected_version") or ""
        mc = (core.extract_mc_version(version_id) if version_id else "") or ""
        loader = self.state.get("mod_loader") or ""
        mods = []
        if mc and loader:
            try:
                mods = p2p.build_mod_list(mc, loader)
            except Exception:
                log.debug("couldn't list local mods for sync", exc_info=True)
        return {"mc_version": mc, "loader": loader, "mods": mods}

    def _sync_get(self, canon: str):
        with self._sync_lock:
            return self._syncs.get(canon)

    def _sync_reap(self) -> None:
        """Close sync rooms nobody is looking at any more.

        Called from the poll path instead of running a janitor thread: the mod
        polls GET /sync about once a second while the view is open, and a view
        that isn't open is exactly the case a timer would be firing for.
        """
        now = time.monotonic()
        stale = []
        with self._sync_lock:
            for canon, rep in list(self._syncs.items()):
                if now - rep["_touched"] > _SYNC_IDLE_S:
                    stale.append((canon, rep.get("_room")))
                    del self._syncs[canon]
                    if rep.get("_room"):
                        self._sync_rooms.pop(rep["_room"], None)
        for _canon, room in stale:
            if room:
                try:
                    self.client.call_end(room)
                except Exception:
                    pass

    def _sync_new(self, name: str, canon: str) -> dict:
        """A fresh report in the 'asking' state, registered as the live sync
        for `canon` (replacing any previous one, whose room is closed)."""
        mine = self._sync_profile()
        rep = {
            "friend": name,
            "state": "asking",
            "error": "",
            "encrypted": False,
            "you": {"version": mine["mc_version"], "loader": mine["loader"],
                    "mods": len(mine["mods"])},
            "them": {"version": "", "loader": "", "mods": 0},
            "version_ok": True,
            "loader_ok": True,
            "missing": [],
            "extra": [],
            "version_licts": [],
            "can_download": False,
            "download_done": 0,
            "download_total": 0,
            "needs_relaunch": False,
            "lines": [f"Asking {self.peer_label(name)} what they're running..."],
            # ---- internals, stripped before this dict is served -------------
            "_room": None,
            "_touched": time.monotonic(),
            "_room_event": threading.Event(),
            "_reply_event": threading.Event(),
            "_chunks": {},        # sha256 -> {"total": int, "parts": {seq: b64}}
            "_chunk_events": {},  # sha256 -> Event set when that jar is whole
            "_gone": set(),       # sha256s the friend said they no longer have
        }
        old_room = None
        evicted_rooms = []
        with self._sync_lock:
            previous = self._syncs.get(canon)
            if previous:
                old_room = previous.get("_room")
                self._sync_rooms.pop(old_room, None)
            self._syncs[canon] = rep
            # A player who opens Sync on eight friends in a row shouldn't leave
            # eight rooms behind; oldest first, same bound as the pending-room map.
            while len(self._syncs) > 8:
                victim_canon, victim = next(iter(self._syncs.items()))
                if victim_canon == canon:
                    break
                del self._syncs[victim_canon]
                self._sync_rooms.pop(victim.get("_room"), None)
                evicted_rooms.append(victim.get("_room"))
        for closed_room in [old_room, *evicted_rooms]:
            if not closed_room:
                continue
            try:
                self.client.call_end(closed_room)
            except Exception:
                pass
        return rep

    def _sync_fail(self, canon: str, message: str) -> None:
        rep = self._sync_get(canon)
        if not rep:
            return
        rep["state"] = "error"
        rep["error"] = message
        rep["can_download"] = False
        rep["_touched"] = time.monotonic()
        rep["_reply_event"].set()
        for ev in list(rep["_chunk_events"].values()):
            ev.set()
        self._sync_render(rep)
        self._changed()

    def _sync_frame(self, peer: str, payload: dict) -> dict:
        """Wrap one sync payload for signal(). Sealed when the encryption
        add-on and the friend's key are both available, plaintext otherwise -
        and the report says which, so the UI is never silently in the clear."""
        mine = self._my_name() or ""
        keypair = self._ensure_e2ee()
        canon = friends.canonical_name(peer) or (peer or "").lower()
        # Use _peer_pubkey which enforces TTL and re-fetches rotated keys.
        # This runs on the sync worker thread, so blocking on FAST_TIMEOUT is OK.
        lookup = self._peer_pubkey(peer)
        if not lookup.get("ok"):
            return {"kind": "cubeon_sync", "open": payload}
        pubkey = lookup["pubkey"]
        if keypair and pubkey and e2ee.is_available():
            try:
                envelope = e2ee.encrypt_dm(keypair[0], pubkey, mine, peer,
                                           json.dumps(payload))
                return {"kind": "cubeon_sync", "sealed": envelope}
            except Exception:
                log.debug("couldn't seal a sync frame", exc_info=True)
        return {"kind": "cubeon_sync", "open": payload}

    def _sync_unwrap(self, data: dict) -> "tuple[dict, bool] | None":
        """(payload, was_encrypted) from an incoming cubeon_sync frame, or None
        if it can't be opened. Decryption is entirely local - the sender's
        ephemeral public key travels inside the envelope - so this is safe on
        the WebSocket thread."""
        opened = data.get("open")
        if isinstance(opened, dict):
            return opened, False
        envelope = data.get("sealed")
        if not isinstance(envelope, dict):
            return None
        mine = self._my_name() or ""
        keypair = self._ensure_e2ee()
        if not mine or not keypair:
            return None
        try:
            return json.loads(e2ee.decrypt_dm(keypair[0], mine, envelope)), True
        except Exception:
            log.debug("dropping an unopenable sync frame", exc_info=True)
            return None

    def _sync_send(self, peer: str, room: str, payload: dict) -> bool:
        if not room:
            return False
        return bool(self.client.signal(room, peer, self._sync_frame(peer, payload)))

    def _sync_render(self, rep: dict) -> None:
        """Pre-render the report as display lines.

        roster_payload() deliberately ships raw fields and lets the mod phrase
        them, but the mod's screen is widget-only (no custom render pass), so
        text can only reach the player through a fixed pool of label widgets.
        Composing these sentences here keeps that pool dumb and keeps the
        wording in one place instead of duplicated across two Java eras.
        """
        lines = []
        state_ = rep["state"]
        you, them = rep["you"], rep["them"]
        if state_ == "asking":
            lines.append(f"Asking {self.peer_label(rep['friend'])} what they're running...")
        elif state_ == "error":
            lines.append(rep["error"] or "Sync failed.")
        else:
            lines.append(f"You: {you['version'] or '?'} {you['loader'] or '?'}"
                         f" - {you['mods']} mods")
            lines.append(f"{self.peer_label(rep['friend'])}: {them['version'] or '?'} "
                         f"{them['loader'] or '?'} - {them['mods']} mods")
            if not rep["version_ok"]:
                lines.append(f"Minecraft version differs. Switch the Play tab to "
                             f"{them['version']} and relaunch to play together.")
            elif not rep["loader_ok"]:
                lines.append(f"Mod loader differs ({you['loader']} vs "
                             f"{them['loader']}). Switch and relaunch.")
            elif not rep["missing"]:
                lines.append("Nothing missing - you can play together as-is.")
            else:
                lines.append(f"You're missing {len(rep['missing'])} of their mods:")
                for entry in rep["missing"][:3]:
                    lines.append("  " + entry["filename"])
                if len(rep["missing"]) > 3:
                    lines.append(f"  ...and {len(rep['missing']) - 3} more")
            conflicts = rep.get("version_licts") or []
            if conflicts:
                lines.append("You have a DIFFERENT version of:")
                for fn in conflicts[:3]:
                    lines.append("  " + fn)
                if len(conflicts) > 3:
                    lines.append(f"  ...and {len(conflicts) - 3} more")
            if rep["extra"]:
                lines.append(f"You have {len(rep['extra'])} mod(s) they don't. "
                             f"That's usually fine.")
            if state_ == "downloading":
                lines.append(f"Downloading {rep['download_done']}"
                             f"/{rep['download_total']}...")
            if rep["needs_relaunch"]:
                lines.append("Done. The host's mods are installed and linked - "
                             "press Fix and relaunch Minecraft to load them.")
            if not rep["encrypted"]:
                lines.append("Note: not encrypted - install the launcher's "
                             "encryption add-on.")
        rep["lines"] = lines

    def sync_start(self, name: str) -> dict:
        """POST /syncstart. Opens the compare channel and returns immediately.

        Everything slow (the friend's key lookup, hashing this machine's jars,
        waiting for their answer) happens on a worker thread, because this runs
        on the local_api request thread the in-game mod is blocking on.
        """
        peer = (name or "").strip()
        if not peer:
            return self._err("Pick a friend to sync with.")
        if not self.client.is_connected:
            return self._err(_NOT_CONNECTED)
        if not self._my_name():
            return self._err("Claim a Cubeon name first.")
        canon = friends.canonical_name(peer) or peer.lower()
        self._sync_reap()
        self._sync_new(peer, canon)
        self._publish_async()
        self._changed()
        threading.Thread(target=self._sync_open, args=(peer, canon),
                         name="cubeon-sync-open", daemon=True).start()
        return self._ok()

    def _sync_open(self, peer: str, canon: str) -> None:
        """Worker half of sync_start: key, room, request, answer."""
        try:
            lookup = self._peer_pubkey(peer)
            if not lookup.get("ok"):
                # Not fatal - an unsealed compare still works, and saying so is
                # more useful than refusing. The report carries encrypted=False.
                log.debug("sync with %s will be unsealed: %s", peer,
                          lookup.get("error"))
            if not self.client.call_invite(peer, kind="sync"):
                self._sync_fail(canon, _NOT_CONNECTED)
                return
            rep = self._sync_get(canon)
            if not rep:
                return
            if not rep["_room_event"].wait(_SYNC_REPLY_TIMEOUT_S):
                self._sync_fail(canon, f"Couldn't open a channel to {self.peer_label(peer)}.")
                return
            if rep["state"] == "error":
                return
            if not self._sync_send(peer, rep["_room"], {"op": "req"}):
                self._sync_fail(canon, _NOT_CONNECTED)
                return
            if not rep["_reply_event"].wait(_SYNC_REPLY_TIMEOUT_S):
                self._sync_fail(canon, f"{self.peer_label(peer)} didn't answer. They may have "
                                       f"closed Minecraft.")
        except Exception as ex:
            log.debug("sync open failed", exc_info=True)
            self._sync_fail(canon, f"Sync failed: {ex}")

    def _sync_answer(self, peer: str, room: str) -> None:
        """Receiver side: seal our own profile back. On a worker thread -
        build_mod_list() hashes every enabled jar and the key lookup may hit
        the network, neither of which belongs on the WebSocket thread."""
        try:
            self._publish_async()
            self._peer_pubkey(peer)   # so the reply can be sealed
            mine = self._sync_profile()
            self._sync_send(peer, room, {
                "op": "reply", "mc_version": mine["mc_version"],
                "loader": mine["loader"], "mods": mine["mods"],
            })
        except Exception:
            log.debug("couldn't answer a sync request", exc_info=True)

    def _sync_on_reply(self, canon: str, payload: dict, encrypted: bool, room=None) -> None:
        rep = self._sync_get(canon)
        if not rep or (room is not None and rep.get("_room") != room):
            return
        mine = self._sync_profile()
        their_mods = [m for m in (payload.get("mods") or []) if isinstance(m, dict)]
        rep["encrypted"] = bool(encrypted)
        rep["you"] = {"version": mine["mc_version"], "loader": mine["loader"],
                      "mods": len(mine["mods"])}
        rep["them"] = {"version": str(payload.get("mc_version") or ""),
                       "loader": str(payload.get("loader") or ""),
                       "mods": len(their_mods)}
        rep["version_ok"] = (bool(mine["mc_version"]) and
                             mine["mc_version"] == rep["them"]["version"])
        rep["loader_ok"] = (bool(mine["loader"]) and
                            mine["loader"] == rep["them"]["loader"])
        try:
            missing = p2p.diff_missing_mods(mine["mods"], their_mods)
        except Exception:
            log.debug("mod diff failed", exc_info=True)
            missing = []
        theirs = {str(m.get("sha256") or "").lower() for m in their_mods}
        rep["missing"] = [m for m in missing if not m.get("sha256") in rep["_gone"]]
        rep["extra"] = sorted(m["filename"] for m in mine["mods"]
                              if m["sha256"].lower() not in theirs)
        # A missing mod whose NAME we already have (a same-stem file with a
        # different hash) is a version clash, not a brand-new mod - call it
        # out so "why do I have a duplicate?" doesn't become the player's job.
        mine_stems = {_mod_stem(m.get("filename"))
                      for m in mine["mods"] if m.get("filename")}
        rep["version_licts"] = sorted({
            m["filename"] for m in rep["missing"]
            if m.get("filename") and _mod_stem(m["filename"]) in mine_stems})
        total_bytes = sum(int(m.get("size") or 0) for m in rep["missing"])
        # Linking a 1.21 friend's jars into a 1.20 profile is how you get a
        # crash on the next launch, so a version/loader mismatch disables the
        # button rather than "helpfully" downloading anyway.
        rep["can_download"] = bool(rep["missing"] and rep["version_ok"]
                                   and rep["loader_ok"]
                                   and total_bytes <= _SYNC_MAX_DOWNLOAD_BYTES)
        rep["download_total"] = len(rep["missing"])
        rep["download_done"] = 0
        rep["state"] = "ready"
        rep["error"] = ""
        rep["_touched"] = time.monotonic()
        rep["_reply_event"].set()
        self._sync_render(rep)
        self._changed()

    def sync_payload(self, friend) -> dict:
        """GET /sync?friend=<name>. The report, minus its internals.

        Returns a plain 'idle' shell when nothing is open for that friend, so
        the mod can poll before pressing Compare without special-casing 404.
        """
        peer = (friend or "").strip()
        canon = friends.canonical_name(peer) or peer.lower()
        self._sync_reap()
        rep = self._sync_get(canon)
        if not rep:
            mine = self._sync_profile()
            return {"friend": peer, "state": "idle", "error": "",
                    "encrypted": e2ee.is_available(),
                    "you": {"version": mine["mc_version"],
                            "loader": mine["loader"], "mods": len(mine["mods"])},
                    "them": {"version": "", "loader": "", "mods": 0},
                    "version_ok": True, "loader_ok": True,
                    "missing": [], "extra": [], "can_download": False,
                    "download_done": 0, "download_total": 0,
                    "needs_relaunch": False,
                    "lines": [f"Compare your Minecraft with {self.peer_label(peer)}'s."]}
        rep["_touched"] = time.monotonic()
        return {k: v for k, v in rep.items() if not k.startswith("_")}

    def sync_download(self, name: str) -> dict:
        """POST /syncdownload. Pull the missing jars into the global mods store
        and link them into the active profile."""
        peer = (name or "").strip()
        canon = friends.canonical_name(peer) or peer.lower()
        rep = self._sync_get(canon)
        if not rep:
            return self._err("Compare first, then download.")
        if rep["state"] == "downloading":
            return self._err("Already downloading.")
        if not rep["missing"]:
            return self._err("Nothing to download.")
        if not rep["version_ok"]:
            return self._err(f"Switch the Play tab to Minecraft "
                             f"{rep['them']['version']} first, then relaunch.")
        if not rep["loader_ok"]:
            return self._err(f"Switch your mod loader to "
                             f"{rep['them']['loader']} first, then relaunch.")
        if not rep["can_download"]:
            return self._err("That's too much to pull over the relay - install "
                             "the modpack instead.")
        if not self.client.is_connected or not rep.get("_room"):
            return self._err(_NOT_CONNECTED)
        rep["state"] = "downloading"
        rep["download_done"] = 0
        rep["download_total"] = len(rep["missing"])
        rep["error"] = ""
        rep["_touched"] = time.monotonic()
        self._sync_render(rep)
        self._changed()
        threading.Thread(target=self._sync_pull, args=(peer, canon),
                         name="cubeon-sync-pull", daemon=True).start()
        return self._ok()

    def _sync_pull(self, peer: str, canon: str) -> None:
        """Worker: one jar at a time - cache hit if we can, ask the friend if
        not. Every jar lands in the global mods store (via p2p's fetch helper)
        and is linked into the profile, which is what actually makes this
        machine compatible."""
        rep = self._sync_get(canon)
        if not rep:
            return
        try:
            core = _core()
            dest_dir = core.get_profile_dir(rep["you"]["version"],
                                            rep["you"]["loader"])
            os.makedirs(dest_dir, exist_ok=True)
            got = 0
            for entry in list(rep["missing"]):
                if self._sync_get(canon) is not rep or rep["state"] != "downloading":
                    return   # closed or restarted under us
                sha = str(entry.get("sha256") or "").lower()
                filename = entry.get("filename") or (sha[:12] + ".jar")
                if not sha:
                    continue
                if p2p.resolve_missing_mod_from_cache(sha, dest_dir, filename):
                    got += 1
                    rep["download_done"] = got
                    rep["_touched"] = time.monotonic()
                    self._sync_render(rep)
                    self._changed()
                    continue
                event = threading.Event()
                rep["_chunk_events"].clear()
                rep["_chunks"].clear()
                rep["_chunk_events"][sha] = event
                rep["_requests"] = {sha: {"room": rep["_room"], "size": entry.get("size", p2p.MOD_MAX_FILE_BYTES)}}
                if not self._sync_send(peer, rep["_room"],
                                       {"op": "modreq", "sha256": sha}):
                    self._sync_fail(canon, _NOT_CONNECTED)
                    return
                if not event.wait(_SYNC_CHUNK_TIMEOUT_S):
                    self._sync_fail(canon, f"{filename} stalled. Try again.")
                    return
                if rep["state"] != "downloading":
                    return
                if sha in rep["_gone"]:
                    continue   # they no longer have it; skip rather than fail
                held = rep["_chunks"].pop(sha, None) or {}
                parts = held.get("parts") or {}
                chunks = [parts[i] for i in sorted(parts)]
                try:
                    p2p.fetch_missing_mod_via_peer(sha, chunks, dest_dir, filename)
                except Exception as ex:
                    self._sync_fail(canon, f"{filename} didn't verify: {ex}")
                    return
                got += 1
                rep["download_done"] = got
                rep["_touched"] = time.monotonic()
                self._sync_render(rep)
                self._changed()
            rep["state"] = "ready"
            # The launcher rebuilds <game dir>/mods from the profile at launch,
            # so a game that's already running is still on the old set.
            rep["needs_relaunch"] = got > 0
            rep["missing"] = [m for m in rep["missing"]
                              if str(m.get("sha256") or "").lower() in rep["_gone"]]
            rep["can_download"] = bool(rep["missing"])
            self._sync_render(rep)
            if got:
                self._notify(f"Downloaded {got} mod(s) from {self.peer_label(peer)}. "
                             f"Relaunch Minecraft to load them.")
            self._changed()
        except Exception as ex:
            log.debug("sync download failed", exc_info=True)
            self._sync_fail(canon, f"Download failed: {ex}")

    def sync_close(self, name: str) -> dict:
        """POST /syncclose. Drops the room so the relay isn't holding one open
        for a view nobody is looking at."""
        peer = (name or "").strip()
        canon = friends.canonical_name(peer) or peer.lower()
        room = None
        with self._sync_lock:
            rep = self._syncs.pop(canon, None)
            if rep:
                room = rep.get("_room")
                rep["state"] = "idle"
                rep["_reply_event"].set()
                for ev in list(rep["_chunk_events"].values()):
                    ev.set()
                self._sync_rooms.pop(room, None)
        if room:
            try:
                self.client.call_end(room)
            except Exception:
                pass
        self._changed()
        return self._ok()

    def ask_join(self, name: str) -> dict:
        """POST /askjoin. The other half of the Play button: rather than
        hosting, nudge the friend to open their world to us.

        A one-shot ping, not a session - the friend's answer is them pressing
        Invite, which arrives as a normal P2P invite through _on_call_invite.
        """
        peer = (name or "").strip()
        if not peer:
            return self._err("Pick a friend to ask.")
        if not self.client.is_connected:
            return self._err(_NOT_CONNECTED)
        if not self.client.call_invite(peer, kind="askjoin"):
            return self._err(_NOT_CONNECTED)
        self._notify(f"Asked {self.peer_label(peer)} to open their world to you.")
        self._changed()
        return self._ok()

    def _on_sync_signal(self, p, data: dict) -> None:
        """The cubeon_sync router. Runs on the WebSocket thread, so every
        branch either mutates a dict or hands off to a worker.

        The receiver keeps no state of its own: `room` and `from` on the frame
        are all it needs to answer, which is why there's no "incoming sync"
        object anywhere in this class.
        """
        room = p.get("room")
        sender = str(p.get("from") or "")
        canon = friends.canonical_name(sender) or sender.lower()
        unwrapped = self._sync_unwrap(data)
        if not unwrapped or not room or not canon:
            return
        payload, encrypted = unwrapped
        op = payload.get("op")
        if op == "req":
            self._sync_rooms[room] = canon
            threading.Thread(target=self._sync_answer, args=(sender, room),
                             name="cubeon-sync-answer", daemon=True).start()
            return
        if op == "reply":
            self._sync_on_reply(canon, payload, encrypted, room)
            return
        if op == "modreq":
            sha = str(payload.get("sha256") or "").lower()

            def serve():
                try:
                    mine = self._sync_profile()
                    profile_dir = _core().get_profile_dir(mine["mc_version"],
                                                          mine["loader"])
                    match = next((m for m in mine["mods"]
                                  if m["sha256"].lower() == sha), None)
                    if not match:
                        self._sync_send(sender, room,
                                        {"op": "modmiss", "sha256": sha})
                        return
                    chunks = p2p.read_chunks_for_mod(
                        os.path.join(profile_dir, match["filename"]))
                    for seq, chunk in enumerate(chunks):
                        self._sync_send(sender, room, {
                            "op": "modchunk", "sha256": sha, "seq": seq,
                            "total": len(chunks), "data_b64": chunk,
                        })
                except Exception:
                    log.debug("couldn't serve a sync mod", exc_info=True)
                    self._sync_send(sender, room,
                                    {"op": "modmiss", "sha256": sha})

            threading.Thread(target=serve, name="cubeon-sync-serve",
                             daemon=True).start()
            return
        rep = self._sync_get(canon)
        sha = str(payload.get("sha256") or "").lower()
        request = (rep or {}).get("_requests", {}).get(sha)
        if (not rep or rep.get("_room") != room or rep.get("state") != "downloading"
                or not request or request.get("room") != room
                or sha not in rep["_chunk_events"]):
            return
        if op == "modchunk":
            if sha not in rep["_chunks"] and len(rep["_chunks"]) >= _MAX_PENDING_ROOMS:
                return
            held = rep["_chunks"].get(sha) or {"size": request["size"]}
            try:
                complete = p2p._accept_chunk(held, payload.get("seq"), payload.get("total"),
                                             payload.get("data_b64"), p2p.MOD_MAX_FILE_BYTES,
                                             p2p.MOD_CHUNK_BYTES)
            except p2p.P2PError:
                return
            rep["_chunks"][sha] = held
            rep["_touched"] = time.monotonic()
            if complete:
                rep["_requests"].pop(sha, None)
                rep["_chunk_events"][sha].set()
            return
        if op == "modmiss":
            sha = str(payload.get("sha256") or "").lower()
            rep["_gone"].add(sha)
            ev = rep["_chunk_events"].get(sha)
            if ev:
                ev.set()
            return

    # =====================================================================
    # Actions. All of these can arrive on a local_api HTTP thread, so nothing
    # here blocks on the network or on a game launch.
    # =====================================================================

    def invite(self, name: str) -> dict:
        """Host side, step 1: launch the game with a log_cb watching for the
        'Open to LAN' line. The invite itself only goes out once the port's
        known - inviting before that would let the joiner accept into a room
        with nothing to connect to yet."""
        peer = (name or "").strip()
        if not peer:
            return self._err("Pick a friend to invite to your world.")
        version_id = self.state.get("selected_version")
        core = _core()
        # Check-and-create under the lock: two mod clicks in the same instant
        # used to be able to build two sessions over each other.
        with self._lock:
            if self._session:
                return self._err("A P2P world session is already running.")
            self._session = {
                "room": None, "peer": peer, "is_host": True,
                "state": "hosting_wait_port", "lan_port": None,
                "punch": None, "error": None,
                "mc_version": core.extract_mc_version(version_id) if version_id else None,
                "loader": self.state.get("mod_loader"),
                "mod_sync": None, "asset_sync": None, "net_ready": False,
                "mods_ready": True, "assets_ready": True,
                "join_launch_started": False, "offer": None, "metrics": {},
            }
        self._changed()

        invited_session = self._session_get()

        def on_port_found(port: int):
            p = self._session_get()
            if p is not invited_session or p.get("state") != "hosting_wait_port":
                return  # cancelled while we were waiting
            p["lan_port"] = port
            # The worldgate decision comes FIRST: the mod shows its password
            # prompt for this state, and the invite only rings out after the
            # host saves a password or skips. Gating the invite itself (not
            # just the offer) is what makes the joiner's "needs password"
            # prompt appear before they commit to anything.
            p["state"] = "gate_wait"
            self._changed()

        log_cb = p2p.watch_for_lan_port(on_port_found)

        def worker():
            try:
                username = self.cfg.get("username") or self._my_name() or "Player"
                version = self.state.get("selected_version")
                if not version:
                    raise RuntimeError("Select a version on the Play tab first.")

                def on_game_exit(returncode, last_lines=None):
                    p = self._session_get()
                    if p is not invited_session:
                        return
                    if p.get("punch"):
                        p["punch"].close()
                    # Tell the joiner we're gone - otherwise their side hangs
                    # on the transport's 30s idle timeout before noticing.
                    if p.get("room"):
                        try:
                            self.client.call_end(p["room"])
                        except Exception:
                            pass
                    # Hosting a world for a friend counts a hosted session
                    # once the LAN world was actually reached (the same bar
                    # the "ended" state uses). Never break the teardown.
                    try:
                        from . import milestones as _milestones
                        _milestones.add_hosted_session()
                    except Exception:
                        pass
                    if p.get("state") == "connected":
                        if returncode in (0, None):
                            p["state"] = "ended"
                            self._changed()
                        else:
                            self._set_failed(
                                p, f"Minecraft closed after hosting (code {returncode}).")
                    else:
                        detail = "Minecraft closed before the LAN world was detected."
                        if returncode not in (0, None):
                            detail = (f"Minecraft exited before the LAN world was "
                                      f"detected (code {returncode}).")
                        if p.get("state") == "gate_wait":
                            detail = ("Minecraft closed before the world "
                                      "password was decided.")
                        self._set_failed(p, detail)

                core.launch_game(
                    version, username, self.cfg["ram_mb"], self.cfg["width"],
                    self.cfg["height"], self.cfg.get("java_path"),
                    on_exit=on_game_exit,
                    mc_version=core.extract_mc_version(version),
                    loader=self.state.get("mod_loader"),
                    cfg=self.cfg, log_cb=log_cb,
                )
            except Exception as ex:
                p = self._session_get()
                if p is invited_session:
                    self._fail_p2p(f"Couldn't start the world: {ex}", p)
                else:
                    self._changed()

        threading.Thread(target=worker, name="p2p-host-launch", daemon=True).start()
        return self._ok()

    # ------------------------------------------------------------------
    # Worldgate: the host's optional LAN-world password and the joiner's
    # proof. See cubeon/worldgate.py for the protocol and why the offer is
    # withheld until a proof lands.
    # ------------------------------------------------------------------

    def _ring_out_pending_invite(self, p: dict) -> bool:
        """Sends the P2P invite the session has been holding in gate_wait.

        Marks the room as a P2P world at invite time, so the receiver lights
        up this friend's Join button immediately (as ringing_out always did)."""
        p["state"] = "ringing_out"
        p["gate_required"] = worldgate.has_password()
        p["gate_authorized"] = not p["gate_required"]
        try:
            sent = self.client.call_invite(p["peer"], kind="p2p")
        except Exception:
            sent = False
        if not sent:
            self._fail_p2p(_NOT_CONNECTED, p)
        self._changed()
        return bool(sent)

    def worldgate_set(self, password: "str | None") -> dict:
        """The host's password decision, from the mod's password prompt.

        password=None (the mod's Skip, or an empty box) leaves the world
        ungated; anything else arms it. Either way, the invite that gate_wait
        was holding now goes out."""
        p = self._session_get()
        if not p or not p.get("is_host"):
            return self._err("You're not hosting a world right now.")
        if p.get("state") != "gate_wait":
            # Idempotent-friendly: a double click on Save after the invite
            # already went out must not re-ring the friend.
            return self._ok()
        if password:
            try:
                worldgate.set_password(password)
            except worldgate.WorldGateError as ex:
                return self._err(str(ex))
            # The password itself is NEVER echoed into chat - a streamer's
            # chat is public. The friend gets asked for it by the gate; the
            # host tells them out of band.
            self._notify(f"Your world is live - {self.peer_label(p['peer'])} has been invited. "
                         f"They'll be asked for the world password.")
        else:
            worldgate.clear()
            self._notify(f"Your world is live - {self.peer_label(p['peer'])} has been invited "
                         f"(no password).")
        if not self._ring_out_pending_invite(p):
            return self._err(_NOT_CONNECTED)
        return self._ok()

    def join(self, name: str) -> dict:
        """Joiner side. Only possible once that friend's invite has actually
        arrived (see _on_call_invite / _on_signal)."""
        peer = (name or "").strip()
        if not peer:
            return self._err("Pick a friend whose world you want to join.")
        conv = friends.canonical_name(peer) or peer.lower()
        with self._lock:
            if self._session:
                return self._err("A P2P world session is already running.")
            room = self._pending_rooms.get(conv)
            if not room:
                return self._err(f"No P2P invite from {self.peer_label(peer)} to join. Ask them "
                                 f"to invite you from their launcher.")
            self._session = {
                "room": room, "peer": peer, "is_host": False,
                "state": "ringing_in", "lan_port": None,
                "punch": None, "error": None,
                "mc_version": None, "loader": None,
                "mod_sync": None, "asset_sync": None, "net_ready": False,
                "mods_ready": False, "assets_ready": False,
                "join_launch_started": False,
            }
            self._pending_rooms.pop(conv, None)
            self._invited_by.discard(conv)
        if not self.client.call_accept(room):
            # The socket dropped between the invite arriving and this click.
            # Roll the whole thing back rather than leaving a session nobody can
            # progress: the host never hears the accept, so no offer will ever
            # come and the mod would sit on "connecting" until the player cancels.
            self._session_set(None)
            self._changed()
            return self._err(_NOT_CONNECTED)
        session = self._session_get()
        if session is not None:
            session["state"] = "connecting"
        self._changed()
        # The host's p2p_offer + p2p_modlist signals (sent right after it sees
        # our accept) carry everything else - handled in _on_signal, which
        # kicks off the punch and the mod sync.
        return self._ok()

    def cancel(self) -> dict:
        self._end_p2p()
        return self._ok()

    def join_password(self, password: str) -> dict:
        """The joiner's typed password for a gated world (POST /joinpassword).

        Stores it on the session just long enough to answer the host's
        challenge; if the challenge has already arrived, answers it now.
        Cleared the moment a proof is sent - a wrong answer means retyping,
        never reusing a stale guess."""
        p = self._session_get()
        if not p or p.get("is_host"):
            return self._err("You're not joining a world right now.")
        # A password is only meaningful while a challenge is outstanding: after
        # gate_ok (or before any arrives) there is nothing to answer, and
        # accepting a typing here would let a stale guess sit on the session.
        if not p.get("gate_challenge") or \
                p.get("state") not in ("password_needed", "connecting"):
            return self._err("Nobody has asked for a password.")
        password = (password or "").strip()
        if not password:
            return self._err("Type the world's password.")
        p["gate_password"] = password
        if p.get("gate_challenge"):
            self._answer_gate_challenge(p)
        else:
            self._changed()
        return self._ok()

    def _answer_gate_challenge(self, p: dict) -> None:
        """Computes and sends the proof for the challenge the session holds.

        The password is dropped as soon as the proof is out: a wrong answer
        means the player types it again, it never lingers for a retry."""
        salt = p.get("gate_salt") or ""
        iterations = p.get("gate_iters") or worldgate.PBKDF2_ITERATIONS
        try:
            proof = worldgate.compute_proof(
                p.get("gate_challenge") or "", p.get("gate_password") or "",
                salt, iterations)
            if p is not self._session_get():
                return
            p["state"] = "connecting"
            self._send_gate(p, {"kind": "gate_proof", "proof_hex": proof})
        except Exception:
            self._fail_p2p("That password can't be used - type it again.", p)
        finally:
            p["gate_password"] = None
        self._changed()

    def retry(self) -> dict:
        p = self._session_get()
        if not p or p.get("is_host") or not p.get("offer"):
            return self._err("There's nothing to retry.")
        offer = p["offer"]
        p["state"] = "connecting"
        p["error"] = None
        p["net_ready"] = False
        p["metrics"] = {}
        self._changed()
        self._run_joiner_punch(offer)
        return self._ok()

    def add_friend(self, target: str) -> dict:
        """Send a friend request, by 8-digit ID (the Chat surface) or by
        Cubeon name (the in-game mod). Answers from local state only.

        This runs on a local_api HTTP request thread that the in-game mod is
        blocking on, so the order of the checks below IS the feature: every one
        of them is a dict lookup or a flag read, and the whole call returns in
        microseconds.

        It used to open with a REST `check_name()` lookup - up to
        friends.TIMEOUT's 15 seconds - purely to reject a typo'd name. That made
        pressing Add look like a hang, and worse: the lookup ran BEFORE the
        "are we even connected?" test, so with the relay unreachable the mod
        waited out the full timeout and then reported the generic "Couldn't
        reach the Cubeon launcher" - blaming the launcher for a network problem.

        A typo still gets its answer: the Worker's own onAdd() replies
        T_SYSTEM 'No Cubeon user named "X".', which arrives through _on_system ->
        _notify -> GET /events and lands on the mod's status line a moment later.
        The server is the authority on which names exist, so asking it twice was
        never worth 15 seconds of dead UI.
        """
        target = (target or "").strip()
        uid = friends.canonical_uid(target)
        if uid:
            return self._add_friend_uid(uid)
        name = target
        ok, err = friends.validate_name(name)
        if not ok:
            return self._err(err)
        if name.lower() == (self._my_name() or "").lower():
            return self._err("You can't add yourself.")
        if not self._my_name():
            return self._err("Claim a Cubeon name before adding friends.")
        if not self.client.is_available:
            return self._err("The launcher is missing its realtime add-on, so "
                             "friend requests can't be sent.")
        if not self.client.is_connected:
            return self._err(_NOT_CONNECTED)
        # Already-known relationships, straight off the cached roster. Saying so
        # here is both instant and more accurate than the server's silence: the
        # Worker drops a duplicate add on the floor, which would leave the mod
        # showing "Friend request sent" for a request it never resent.
        canon = friends.canonical_name(name) or name.lower()
        roster = self.client.roster or {}
        for entry in (roster.get("friends") or []):
            if not isinstance(entry, dict):
                continue
            other = entry.get("name") or ""
            if (friends.canonical_name(other) or other.lower()) == canon:
                return self._err(f"{self.peer_label(other)} is already your friend.")
        for pending in (roster.get("requests_out") or []):
            if isinstance(pending, str) and \
                    (friends.canonical_name(pending) or pending.lower()) == canon:
                return self._err(f"You've already asked {self.peer_label(pending)}. "
                                 f"Waiting on their answer.")
        for incoming in (roster.get("requests_in") or []):
            if isinstance(incoming, str) and \
                    (friends.canonical_name(incoming) or incoming.lower()) == canon:
                # The Worker turns an add into an accept in exactly this case;
                # tell the truth about what the button just did.
                if not self.client.add_friend(name):
                    return self._err(_NOT_CONNECTED)
                self._notify(f"{self.peer_label(incoming)} asked you first - you're friends now.")
                self._changed()
                return self._ok()
        if not self.client.add_friend(name):
            return self._err(_NOT_CONNECTED)
        self._notify(f"Friend request sent to {self.peer_label(name)}.")
        self._changed()
        # Guaranteed answer for a typo'd or unclaimed name. The relay normally
        # replies T_SYSTEM 'No Cubeon user named "X".' on its own, but that
        # only exists in newer Worker deployments - an older relay drops the
        # add silently and the player never learns anything. A bounded REST
        # lookup here, off the request thread, closes that gap; _notify's
        # dedupe keeps the player from seeing the answer twice when both
        # sources fire.
        threading.Thread(target=self._verify_add, args=(name,),
                         name="cubeon-add-verify", daemon=True).start()
        return self._ok()

    def _verify_add(self, name: str) -> None:
        """Worker half of the add fallback: does that name exist at all?"""
        try:
            lookup = self.client.check_name(name)
        except Exception:
            log.debug("add-verify lookup failed", exc_info=True)
            return
        if not (isinstance(lookup, dict) and lookup.get("ok")):
            return   # the lookup itself failed - nothing to add
        if lookup.get("exists"):
            self._remember_metadata(lookup, name)
            return
        self._notify("That Cubeon player couldn't be found. Check their Cubeon ID.",
                     error=True)

    def _add_friend_uid(self, uid: str) -> dict:
        """The UID half of add_friend(). Kept separate because the "already
        your friend" test matches on the friend's stored uid, not a name - the
        Chat surface no longer knows or needs the name to add someone."""
        if uid == (self._my_uid() or ""):
            return self._err("You can't add yourself.")
        if not self._my_name():
            return self._err("Claim a Cubeon name before adding friends.")
        if not self.client.is_available:
            return self._err("The launcher is missing its realtime add-on, so "
                             "friend requests can't be sent.")
        if not self.client.is_connected:
            return self._err(_NOT_CONNECTED)
        adder = getattr(self.client, "add_friend_uid", None)
        if adder is None:
            return self._err("The launcher needs an update to add friends by ID.")
        roster = self.client.roster or {}
        for entry in (roster.get("friends") or []):
            if isinstance(entry, dict) and friends.canonical_uid(entry.get("uid")) == uid:
                other = entry.get("name") or ""
                return self._err(f"{self.peer_label(other)} is already your friend."
                                 if other else "You've already added that friend.")
        if not adder(uid):
            return self._err(_NOT_CONNECTED)
        self._notify(f"Friend request sent to ID {uid}.")
        self._changed()
        # Same guarantee as the name path: a typo'd ID gets an answer even on an
        # older relay that drops an unknown add silently.
        threading.Thread(target=self._verify_add_uid, args=(uid,),
                         name="cubeon-add-verify-uid", daemon=True).start()
        return self._ok()

    def _verify_add_uid(self, uid: str) -> None:
        """Worker half of the add-by-ID fallback: does that ID exist at all?"""
        checker = getattr(self.client, "check_uid", None)
        if checker is None:
            return
        try:
            lookup = checker(uid)
        except Exception:
            log.debug("add-verify uid lookup failed", exc_info=True)
            return
        if not (isinstance(lookup, dict) and lookup.get("ok")):
            return   # the lookup itself failed - nothing to add
        if lookup.get("exists"):
            self._remember_metadata(lookup)
            self._changed()
            return
        self._notify(f"No Cubeon user with ID {uid}.", error=True)

    def accept(self, name: str) -> dict:
        return self._forward(self.client.accept_request, name)

    def decline(self, name: str) -> dict:
        return self._forward(self.client.decline_request, name)

    def remove(self, name: str) -> dict:
        """Drop a friend in both directions. The Friends tab never called
        client.remove_friend at all - there was no button for it."""
        return self._forward(self.client.remove_friend, name)

    def _forward(self, sender, name: str) -> dict:
        name = (name or "").strip()
        ok, err = friends.validate_name(name)
        if not ok:
            return self._err(err)
        if not sender(name):
            return self._err(_NOT_CONNECTED)
        self._changed()
        return self._ok()

    def set_whitelisted(self, name: str, on: bool) -> dict:
        """One tap adds/removes this friend on the selected server's
        whitelist.json (live via the console when the server is running).

        The whitelist is keyed by MINECRAFT username: the relay handle the
        bridge sends must first resolve to the friend's validated
        minecraft_username, and a friend with no known username is refused
        rather than silently whitelisting a name the game would never see
        (S12)."""
        name = (name or "").strip()
        if not name:
            return self._err("Which friend?")
        version_id = self.state.get("selected_version")
        if not version_id:
            return self._err("Install a server first (Servers tab) to manage "
                             "its whitelist.")
        meta = self.peer_metadata(name)
        mc_name = friends.minecraft_username(meta.get("minecraft_username"))
        if not mc_name:
            return self._err(f"{self.peer_label(name)} has no known Minecraft "
                             f"username to whitelist yet.")
        core = _core()
        try:
            if on:
                core.add_to_whitelist(version_id, mc_name)
                self._notify(f"{self.peer_label(name)} is whitelisted. Only whitelisted players "
                             f"can join while the gate is on.")
            else:
                core.remove_from_whitelist(version_id, mc_name)
                self._notify(f"{self.peer_label(name)} removed from the server whitelist. They "
                             f"can no longer join.")
        except ValueError as ex:
            return self._err(str(ex))
        except Exception as ex:
            return self._err(f"Couldn't update the whitelist: {ex}")
        self._changed()
        return self._ok()

    def rename(self, name: str) -> dict:
        return self._err("Change your Minecraft username in the launcher. "
                         "Your Cubeon ID and friends stay the same.")

    def rename_unique(self, base: str) -> dict:
        return self.rename(base)

    def _finish_rename(self, name: str, was: str) -> dict:
        return self.rename(name)

    # =====================================================================
    # P2P worlds (cubeon/p2p.py, roadmap Phase 2b). Host and joiner share one
    # session dict but take different paths through it:
    #
    #   Host:   invite() launches the game with a log_cb watching for the
    #           LAN-open line -> once the port's known, call_invite(friend) ->
    #           on accept, send a p2p_offer signal with the port + our STUN
    #           candidate -> hole-punch in the background while serving the mod
    #           requests the joiner sends back.
    #   Joiner: join() accepts a pending invite, then the host's p2p_offer /
    #           p2p_modlist / p2p_assetlist signals drive hole-punching and the
    #           mod+asset diff in parallel; the game only launches once both
    #           finish. On leaving, teardown() strips this session's mod
    #           symlinks from the active profile and nothing else.
    #
    # Failure NEVER offers "host a dedicated server instead"; that's a
    # different feature (Server tab) - see p2p.py.
    # =====================================================================

    def _set_failed(self, p: dict, message: str) -> None:
        """Move a session to `failed` and say so. The banner used to be the
        only place a failure appeared; with no banner, a silent failure would
        just look like a hang, so every one of them is also a notification."""
        p["state"] = "failed"
        p["error"] = message
        self._notify(message, error=True)
        self._changed()

    def _cancel_syncs(self, p):
        p["gate_password"] = None
        for key in ("mod_sync", "asset_sync"):
            sync = p.get(key)
            if sync and hasattr(sync, "cancel"):
                sync.cancel()

    def _transport_allowed(self, p):
        if p is not self._session_get() or p.get("state") in ("failed", "ended"):
            return False
        required = p.get("gate_required", bool(p.get("is_host") and worldgate.has_password()))
        return not required or p.get("gate_authorized") is True

    def _fail_p2p(self, message: str, expected=None) -> None:
        p = self._session_get()
        if expected is not None and p is not expected:
            return
        if p:
            self._cancel_syncs(p)
            room = p.get("room")
            if p.get("punch"):
                p["punch"].close()
            if room and not p.get("is_host"):
                p2p.teardown(room)
            if room:
                try:
                    self.client.call_end(room)
                except Exception:
                    pass
            self._set_failed(p, message)
            # The world password was armed for THIS session only - a failed
            # one (wrong password exhausted, joiner vanished) must not leave
            # it guarding the next world.
            worldgate.clear()
        else:
            self._notify(message, error=True)

    def _record_links(self, p: dict, mc_version, loader) -> None:
        """p2p.record_session_links() with the mod/asset halves read off
        whichever sync sessions exist - the tab spelled this out at six call
        sites. Wrapped because an OSError writing the session file used to kill
        the calling worker thread *before* it set mods_ready/assets_ready,
        which left the join stuck on "connecting" forever."""
        try:
            p2p.record_session_links(
                p.get("room"), mc_version, loader,
                getattr(p.get("mod_sync"), "linked_paths", []),
                getattr(p.get("mod_sync"), "disabled_paths", []),
                getattr(p.get("asset_sync"), "added_paths", []),
                getattr(p.get("asset_sync"), "backups", []),
            )
        except Exception:
            log.warning("couldn't record P2P session links for room %r",
                        p.get("room"), exc_info=True)

    def _end_p2p(self) -> None:
        """User-initiated cancel/leave. Sends call_end so the peer's side tears
        down too; actual local cleanup (closing the punch socket, stripping
        this session's mod symlinks) happens in _on_call_end so there's exactly
        one teardown path whether we or the peer hung up."""
        p = self._session_get()
        if not p:
            return
        self._cancel_syncs(p)
        room = p.get("room")
        self._on_call_end({"room": room})
        if room:
            try:
                self.client.call_end(room)
            except Exception:
                pass

    def _watch_p2p_transport(self, session, room) -> None:
        """Surface transport failures instead of leaving the UI looking
        connected after the peer socket has died or timed out. Also fires the
        one-shot relay/direct notices for hybrid sessions."""
        def worker():
            last_change = 0.0
            prev_mode = None
            while not _wait_session_closed(session, 0.5):
                current = self._session_get()
                if not current or current.get("room") != room \
                        or current.get("punch") is not session:
                    return
                current["metrics"] = session.metrics()
                mode = (current.get("metrics") or {}).get("mode")
                if isinstance(session, p2p.HybridSession) and \
                        current.get("state") in ("connected", "launching"):
                    if getattr(session, "punch_failed_round", False) and mode == "relay" \
                            and not current.get("_relay_notice_shown"):
                        # The coordinated punch had a fair chance and didn't
                        # land. The host now decides the fallback: Minekube if
                        # their public server is up, the Cubeon relay only when
                        # there's nothing to fall back TO.
                        current["_relay_notice_shown"] = True
                        if current.get("is_host"):
                            self._switch_to_minekube("direct connection failed")
                        else:
                            self._notify(f"Couldn't open a direct connection to "
                                         f"{self.peer_label(current['peer'])} - the world is on "
                                         f"Cubeon's relay (higher ping, same "
                                         f"world).")
                    elif prev_mode in ("relay", "handover") and mode == "direct":
                        self._notify(f"Direct connection to {self.peer_label(current['peer'])} "
                                     f"established. Ping just improved.")
                prev_mode = mode
                # The old tab repainted the banner at most every 2s; the same
                # throttle keeps the revision counter from churning once per
                # metrics tick for the whole session.
                now = time.monotonic()
                if now - last_change >= 2.0:
                    last_change = now
                    self._changed()
            current = self._session_get()
            if not current or current.get("room") != room \
                    or current.get("punch") is not session:
                return
            current["metrics"] = session.metrics()
            if current.get("state") in ("connected", "launching") and session.closed_reason:
                self._fail_p2p(session.closed_reason)

        threading.Thread(target=worker, name="cubeon-p2p-watchdog",
                         daemon=True).start()

    def _maybe_finish_join(self) -> None:
        """Joining only happens once the network path, the mod sync AND the
        asset sync all report ready. Then launch Minecraft straight into the
        local relay so the player never has to open Direct Connect manually."""
        p = self._session_get()
        if not p or p.get("is_host") or p.get("state") != "connecting":
            return
        if not (p["net_ready"] and p["mods_ready"] and p.get("assets_ready", True)):
            return
        if p.get("join_launch_started"):
            return

        # Minekube fallback: no local relay port - the joiner connects to the
        # host's public server like any normal multiplayer server.
        minekube_addr = None
        relay_port = None
        if p.get("minekube_active"):
            minekube_addr = p.get("minekube_address") or ""
            if not minekube_addr:
                self._fail_p2p("The Minekube fallback was chosen but no server "
                               "address arrived.")
                return
        else:
            relay_port = p.get("punch").local_relay_port if p.get("punch") else None
            if not relay_port:
                self._fail_p2p("The direct connection succeeded, but the local "
                               "relay did not start.")
                return

        p["state"] = "launching"
        p["join_launch_started"] = True
        self._changed()

        def worker():
            core = _core()
            try:
                version_id = self.state.get("selected_version")
                if not version_id:
                    raise RuntimeError("Select a Minecraft version before joining.")
                username = self.cfg.get("username") or self._my_name() or "Player"
                mc_version = p.get("mc_version") or core.extract_mc_version(version_id)
                loader = p.get("loader") or self.state.get("mod_loader")
                if not mc_version or not loader:
                    raise RuntimeError("The P2P session did not provide a valid "
                                       "Minecraft profile.")

                def on_game_exit(returncode, last_lines=None):
                    current = self._session_get()
                    if not current or current.get("room") != p.get("room"):
                        return
                    if current.get("punch"):
                        current["punch"].close()
                    # Tell the host we're gone - otherwise their side waits on
                    # the transport's 30s idle timeout before noticing.
                    if current.get("room"):
                        try:
                            self.client.call_end(current["room"])
                        except Exception:
                            pass
                    if not current.get("is_host") and current.get("room"):
                        p2p.teardown(current["room"])
                    if returncode in (0, None):
                        current["state"] = "ended"
                        self._changed()
                    else:
                        self._set_failed(
                            current,
                            f"Minecraft closed after joining (code {returncode}).")

                if minekube_addr:
                    mc_host, _, mc_port = minekube_addr.partition(":")
                    launch_target = dict(
                        server_address=mc_host,
                        server_port=int(mc_port) if mc_port.strip().isdigit() else 25565,
                    )
                else:
                    launch_target = dict(server_address="127.0.0.1",
                                         server_port=relay_port)
                core.launch_game(
                    version_id, username, self.cfg["ram_mb"], self.cfg["width"],
                    self.cfg["height"], self.cfg.get("java_path"),
                    on_exit=on_game_exit, mc_version=mc_version, loader=loader,
                    cfg=self.cfg, **launch_target,
                )
            except Exception as ex:
                self._fail_p2p(f"Couldn't launch Minecraft into the P2P world: {ex}")

        threading.Thread(target=worker, name="p2p-auto-join-launch",
                         daemon=True).start()

    def _switch_to_relay(self, reason: str = "") -> None:
        """Shared fallback path (host AND joiner): tear down the punch session -
        successful or not; a one-way punch is useless to Minecraft's
        bidirectional stream - and carry the same TCP stream over the friends
        signalling channel instead. Idempotent: whoever notices the failure
        first sends p2p_use_relay and switches locally, the other side switches
        on receiving that signal."""
        p = self._session_get()
        if not p or p.get("relay_active"):
            return
        if p.get("is_host") and not self._transport_allowed(p):
            self._fail_p2p("The world password was never verified - not falling "
                           "back to the relay.", p)
            return
        p["relay_active"] = True
        # The reason used to be accepted and dropped on the floor, so a user
        # watching a session silently get slower had no idea why.
        if reason:
            self._notify(f"Playing through the Cubeon relay instead: {reason}.")
        if p.get("punch"):
            p["punch"].close()
            p["punch"] = None

        def bound(payload):
            self.client.signal(p["room"], p["peer"], payload)

        rs = p2p.RelaySession(is_host=p["is_host"], lan_port=p.get("lan_port"),
                              send_signal=bound)
        rs.start()
        p["punch"] = rs
        p["net_ready"] = True   # the "network" is ready by construction now
        self._watch_p2p_transport(rs, p["room"])
        if not p["is_host"]:
            # Joiner: mirror the punch-success flow - state must be
            # "connecting" for _maybe_finish_join() to fire.
            if not p.get("join_launch_started"):
                p["state"] = "connecting"
            self._changed()
            self._maybe_finish_join()
        else:
            p["state"] = "connected"
            self._changed()

    def _switch_to_minekube(self, reason: str = "") -> None:
        """Host-side, after the direct P2P punch has failed.

        THE WORLD STAYS ON CUBEON'S RELAY. The HybridSession has already
        fallen back to relaying the world's TCP stream through the signalling
        channel, so the joiner still lands in the LAN world - just with
        higher ping. Minekube's public address is deliberately NOT used as
        the join target: the Connect plugin is a tunnel for the host's PAPER
        SERVER, so a friend pointed at <endpoint>.play.minekube.net would
        land in the server's world, not this one. The address is announced
        into the host's Minecraft chat instead, as a copyable share for the
        Cubeon server itself (an older launcher may still hand its joiner
        there - see the p2p_use_minekube handler, kept for that).
        """
        p = self._session_get()
        if not p or not p.get("is_host"):
            return
        if reason:
            self._notify(f"Direct connection failed - staying on Cubeon's "
                         f"relay ({reason}).")

        core = _core()
        version_id = self.state.get("selected_version")
        address = None
        if version_id and core.is_server_running(version_id):
            address = core.minekube.read_public_address(version_id)
            if not address:
                address = core.minekube.public_address(
                    core.minekube.get_endpoint(version_id))
        if address:
            # The one place the address is printed for the host: their own
            # Minecraft chat, where it can be copied and shared. It shares
            # the Cubeon SERVER - say so, so nobody expects their LAN world
            # to be behind it.
            self._notify(f"Your Cubeon server is also public at {address} - "
                         f"share that for friends joining WITHOUT Cubeon. "
                         f"This world stays right here.")
        else:
            self._notify("Start your Paper server with public sharing "
                         "(Servers tab) if you also want a public address "
                         "for the Cubeon server.")
        self._changed()

    def _run_joiner_punch(self, offer: dict) -> None:
        """Called from the WebSocket thread's dispatch of the p2p_offer signal.
        Hands off to a background thread immediately - hole-punching blocks for
        up to PUNCH_ATTEMPT_S and must never stall the socket thread that every
        other friend event also rides. Mod sync is started separately (see
        _on_signal's p2p_modlist branch) so a slow punch never holds it up."""
        p = self._session_get()
        if not p or p.get("state") != "connecting":
            return
        p["offer"] = dict(offer)

        def worker():
            try:
                if offer.get("transport") == p2p.HYBRID_TRANSPORT_TAG:
                    self._run_joiner_hybrid(offer)
                    return
                # --- legacy dialect: an older Cubeon build is hosting -------
                if offer.get("transport") != "cubeon-tcp-over-udp-v2":
                    raise p2p.P2PError("Your friend's Cubeon build uses an "
                                       "incompatible P2P transport. Update both "
                                       "launchers.")
                token_hex = offer.get("session_token") or ""
                try:
                    session_token = bytes.fromhex(token_hex)
                except (TypeError, ValueError):
                    raise p2p.P2PError("The P2P session token from your friend "
                                       "was invalid.")
                # A retry replaces a failed session - close the old one first so
                # its punch/transport threads stop firing at the peer and its
                # socket doesn't leak for the rest of the process.
                old = p.get("punch")
                if old is not None:
                    old.close()
                    p["punch"] = None
                session = p2p.PunchSession(is_host=False, session_token=session_token)
                p["punch"] = session
                local_candidate = session.get_local_candidate()
                self.client.signal(p["room"], p["peer"], {
                    "kind": "p2p_answer", "stun_candidate": local_candidate,
                    "relay": True,   # this build can fall back to the signalling relay
                })
                session.connect(offer["stun_candidate"])
                p["net_ready"] = True
                self._watch_p2p_transport(session, p["room"])
                self._maybe_finish_join()
            except p2p.P2PError as e:
                # Punch failed - CGNAT/symmetric NAT makes direct impossible.
                # If the host advertised relay support, fall back instead of
                # failing the join outright.
                #
                # This used to read ui.get("p2p", {}).get("state"): "p2p" is
                # always present but may be None, so the .get() raised
                # AttributeError *inside* this handler, killing the thread and
                # leaving the session stuck on "connecting" with nothing said.
                current = self._session_get() or {}
                if offer.get("relay") and current.get("state") == "connecting":
                    try:
                        self.client.signal(current.get("room"), current.get("peer"),
                                           {"kind": "p2p_use_relay"})
                    except Exception:
                        pass
                    self._switch_to_relay(reason=str(e))
                else:
                    self._fail_p2p(str(e))
            except Exception as e:
                self._fail_p2p(f"Unexpected error: {e}")

        threading.Thread(target=worker, name="p2p-joiner-punch", daemon=True).start()

    def _run_joiner_hybrid(self, offer: dict) -> None:
        """New-dialect join path (Relayed Signalling + Direct Hole-Punch
        Handover). Runs on the background thread _run_joiner_punch started. The
        relay pipe is up within a second - network-ready - and the coordinated
        punch/handover proceeds in the background. A punch that never lands is
        NOT an error anymore; the session just stays relayed."""
        p = self._session_get()
        if not p:
            return  # cancelled between the offer arriving and this thread running
        token_hex = offer.get("session_token") or ""
        try:
            session_token = bytes.fromhex(token_hex)
        except (TypeError, ValueError):
            raise p2p.P2PError("The P2P session token from your friend was invalid.")
        # A retry replaces a failed session - close the old one first so its
        # threads stop firing at the peer and its socket doesn't leak.
        old = p.get("punch")
        if old is not None:
            old.close()
            p["punch"] = None

        def bound(payload):
            self.client.signal(p["room"], p["peer"], payload)

        session = p2p.HybridSession(is_host=False, session_token=session_token,
                                    send_signal=bound)
        p["punch"] = session
        session.begin()   # strategy step 1: guaranteed relay pipeline
        self._watch_p2p_transport(session, p["room"])
        try:
            probe = p2p.probe_nat(session.udp_socket)   # strategy step 2
            nat_info = {
                "candidate": {"ip": probe["ip"], "port": probe["port"]},
                "symmetric": probe["symmetric"],
                "delta": probe["delta"],
                "probes": probe["probes"],
            }
            candidate = nat_info["candidate"]
        except p2p.P2PError:
            nat_info, candidate = None, None
        self.client.signal(p["room"], p["peer"], {
            "kind": "p2p_answer", "stun_candidate": candidate,
            "nat_info": nat_info,
            "transport": p2p.HYBRID_TRANSPORT_TAG,
        })
        p["net_ready"] = True   # the relay carries the stream already
        if nat_info:
            # Strategy steps 3+4: coordinated spray + handover, all in the
            # background. Host arms the rounds once it sees this answer.
            session.begin_punch(nat_info, offer.get("nat_info"))
        self._maybe_finish_join()

    def _run_host_punch(self, answer: dict) -> None:
        """Host side, triggered by the joiner's p2p_answer signal. For a
        new-dialect joiner this just feeds their NAT diagnostics into the
        already-running HybridSession - the coordinated spray starts there. For
        a legacy joiner (old build) it completes a classic PunchSession
        connect() with the joiner's candidate, in a background thread since that
        blocks for up to PUNCH_ATTEMPT_S."""
        p = self._session_get()
        session = p.get("punch") if p else None
        if isinstance(session, p2p.HybridSession) and \
                answer.get("transport") == p2p.HYBRID_TRANSPORT_TAG:
            session.begin_punch(p.get("_nat_probe") or {}, answer.get("nat_info"))
            return
        if not p or not p.get("punch"):
            return
        if p.get("is_host") and not self._transport_allowed(p):
            self._fail_p2p("The world password was never verified - not falling "
                           "back to the relay.", p)
            return
        p["state"] = "connecting"
        self._changed()

        def worker():
            try:
                p["punch"].connect(answer["stun_candidate"])
                p["net_ready"] = True
                self._watch_p2p_transport(p["punch"], p["room"])
                p["state"] = "connected"
                self._changed()
            except p2p.P2PError as e:
                # Our punch failed - ask the joiner to switch both sides to the
                # signalling relay (they may still be mid-punch; the
                # p2p_use_relay signal overrides whatever they conclude). Only
                # if the joiner's answer advertised relay support.
                if answer.get("relay"):
                    try:
                        self.client.signal(p["room"], p["peer"],
                                           {"kind": "p2p_use_relay"})
                    except Exception:
                        pass
                    self._switch_to_relay(reason=str(e))
                else:
                    self._fail_p2p(str(e))
            except Exception as e:
                self._fail_p2p(f"Unexpected error: {e}")

        threading.Thread(target=worker, name="p2p-host-punch", daemon=True).start()

    # =====================================================================
    # Client callbacks - all fire on the WebSocket thread. Keep them short;
    # anything slow goes to a worker.
    # =====================================================================

    def _on_state(self, payload) -> None:
        if isinstance(payload, dict) and payload.get("connected"):
            with self._chat_lock:
                self._connect_gen += 1
                for canon, seeded in self._chat_seeded.items():
                    if seeded != "done":
                        self._chat_seeded[canon] = "retry"
            # A reconnect re-resolves peer keys on next use: a friend who
            # rotated their key while we were offline must not keep receiving
            # messages sealed to the cached dead key (S15).
            with self._metadata_lock:
                self._peer_pubkeys.clear()
            self.reconcile_username()
        self._changed()

    def _on_roster(self, payload) -> None:
        self._remember_roster(payload)
        self._remember_roster(self.client.roster)
        self._changed()

    def _on_presence(self, p) -> None:
        self._remember_event(p)
        canon = friends.canonical_name(p.get("name") or "")
        if canon:
            for friend in ((self.client.roster or {}).get("friends") or []):
                if not isinstance(friend, dict):
                    continue
                if friends.canonical_name(friend.get("name") or "") != canon:
                    continue
                for field in ("online", "version", "status"):
                    if field in p and friend.get(field) != p[field]:
                        friend[field] = p[field]
        self._remember_roster(self.client.roster)

    def _on_request(self, p) -> None:
        self._remember_roster(self.client.roster)
        self._remember_event(p)
        self._notify(f"{self.peer_label(p.get('from'))} sent you a friend request.")

    def _on_friend_added(self, p) -> None:
        self._remember_event(p)
        self._notify(f"{self.peer_label(p.get('name'))} accepted your friend request.")

    def _on_friend_removed(self, p) -> None:
        self._remember_event(p)
        self._notify(f"{self.peer_label(p.get('name'))} removed you.", error=True)

    def _on_system(self, p) -> None:
        self._remember_event(p)
        self._notify(self._relay_notice(p), error=True)

    def _on_error(self, p) -> None:
        self._remember_event(p)
        messages = {
            "rate_limited": "Too many requests. Try again in a moment.",
            "dm_bad_recipient": "Pick a friend to message.",
            "dm_empty": "Type a message first.",
            "dm_too_large": "Message too long to send. Try a shorter one.",
            "dm_not_friends": "Add this player as a friend before messaging.",
        }
        self._notify(messages.get(p.get("code"),
                                  "Couldn't complete that request. Try again."),
                     error=True)

    def _relay_notice(self, payload, peer=None) -> str:
        text = str(payload.get("message") or payload.get("text") or "")
        target = peer or payload.get("peer") or payload.get("to") or payload.get("from")
        if "offline" in text.lower():
            return f"{self.peer_label(target)} is offline."
        if text.startswith("No Cubeon user with ID "):
            uid = friends.canonical_uid(text[len("No Cubeon user with ID "):].rstrip("."))
            if uid:
                return f"No Cubeon user with ID {uid}."
        if text.startswith("No Cubeon user named "):
            return "That Cubeon player couldn't be found. Check their Cubeon ID."
        return "The friends server couldn't complete that action. Try again."

    def _on_call_invite(self, p) -> None:
        self._remember_event(p)
        room = p.get("room")
        kind = p.get("kind")
        if p.get("outgoing"):
            # Our own invite got a room id back. A sync/askjoin room is ours by
            # construction, so claim it before the P2P branch gets a look in:
            # both of those exist without a session, and _session_get() would
            # otherwise hand a compare room to whatever world is live.
            if kind in ("sync", "askjoin"):
                to = str(p.get("to") or "")
                canon = friends.canonical_name(to) or to.lower()
                if room:
                    self._sync_rooms[room] = canon
                rep = self._sync_get(canon)
                if kind == "sync" and rep:
                    rep["_room"] = room
                    rep["_room_event"].set()
                return
            # Could be a voice call or a P2P host invite (invite() already
            # created the session with room=None before sending call_invite) -
            # route to whichever is actually waiting on this room id.
            pr = self._session_get()
            if pr and pr.get("room") is None and pr.get("state") == "ringing_out":
                pr["room"] = room
                self._changed()
            return
        # Incoming ring. P2P invites are explicitly marked by the sender, so
        # they can light up the targeted friend's Join button immediately.
        conv = friends.canonical_name(p.get("from", "")) or (p.get("from") or "").lower()
        if kind == "p2p":
            if self._session_get():
                self.client.call_decline(room)
                return
            self._remember_pending(conv, room)
            self._notify(f"{self.peer_label(p.get('from'))} invited you to a P2P world.")
            self._changed()
            return
        if kind == "sync":
            # A friend wants to compare profiles. The Worker already put both of
            # us in the room, so there is nothing to accept - just keep the room
            # (deliberately NOT in _pending_rooms, which only holds joinable
            # worlds) and let the sealed request that follows do the work. It
            # must not be declined: declining deletes the room server-side.
            if room:
                self._sync_rooms[room] = conv
            return
        if kind == "askjoin":
            # "Can I play?" - a ping, not a session. Answering is the player
            # pressing Invite, so close the room immediately rather than leave
            # one open per ask.
            self._notify(f"{self.peer_label(p.get('from'))} wants to join your world - "
                         f"press Invite on their row.")
            self._changed()
            if room:
                self.client.call_end(room)
            return
        # Anything that isn't an explicit P2P invite is a legacy voice call -
        # voice UI was removed with chat, so politely decline.
        self.client.call_decline(room)

    def _on_call_accept(self, p) -> None:
        room = p.get("room")
        pr = self._session_get()
        if not (pr and pr.get("room") == room and pr.get("is_host")):
            return

        # Joiner accepted. If the world is password-gated, the connection
        # target stays secret until they prove they know it: the p2p_offer
        # carries the LAN port and the relay session token, so sending it to
        # an unproven peer would make the gate decorative.
        if worldgate.has_password():
            self._host_send_gate_challenge(pr)
            return

        # Ungated (the host pressed Skip): straight to the offer. This is the
        # frame that actually marks the room as a P2P session rather than a
        # voice call, on both sides.
        self._send_p2p_offer(pr, room)

    def _send_gate(self, pr, payload):
        try:
            mine = self._my_name()
            keys = self._ensure_e2ee()
            peer = pr["peer"]
            pub = self._peer_pubkey(peer).get("pubkey")
            if not mine or not keys or not pub or not e2ee.is_available():
                raise ValueError("Encryption unavailable")
            body = dict(payload, room=pr["room"])
            envelope = e2ee.encrypt_dm(keys[0], pub, mine, peer, json.dumps(body))
            if pr is not self._session_get():
                return False
            if not self.client.signal(pr["room"], peer, {"kind": payload["kind"], "sealed": envelope}):
                raise ValueError("Signal unavailable")
            return True
        except Exception:
            self._fail_p2p("Couldn't securely check the world password. Reopen both launchers and try again.", pr)
            return False

    def _open_gate(self, pr, frame):
        try:
            data = frame.get("data") or frame
            envelope = data["sealed"]
            mine = self._my_name()
            keys = self._ensure_e2ee()
            if not mine or not keys:
                return None
            peer = str(envelope.get("from") or "")
            canon = friends.canonical_name(peer) or peer.lower()
            if (pr.get("room") is None and canon != (friends.canonical_name(pr.get("peer") or "")
                                                     or (pr.get("peer") or "").lower())):
                return None
            body = json.loads(e2ee.decrypt_dm(keys[0], mine, envelope))
            if str(body.get("kind") or "") != str(data.get("kind") or ""):
                return None
            room = body.get("room") if pr.get("room") is None else pr.get("room")
            if room is not None and body.get("room") != room:
                return None
            return body
        except Exception:
            return None

    def _host_send_gate_challenge(self, pr: dict) -> None:
        """One challenge round, host side. Fresh 128-bit nonce per round, so a
        proof can never be replayed into a later session."""
        challenge = worldgate.new_challenge()
        pr["gate_challenge"] = challenge
        pr["gate_attempts"] = pr.get("gate_attempts") or 0
        pr["state"] = "verifying"
        record = worldgate.record()
        if not self._send_gate(pr, {
            "kind": "gate_challenge", "challenge": challenge,
            "salt_hex": record["salt_hex"] if record else "",
            "iterations": record["iterations"] if record
                          else worldgate.PBKDF2_ITERATIONS,
        }):
            return
        self._changed()
        threading.Thread(target=self._gate_challenge_watchdog,
                         args=(pr["room"], challenge),
                         name="cubeon-gate-watchdog", daemon=True).start()

    def _gate_challenge_watchdog(self, room: str, challenge: str) -> None:
        """Closes the room if no proof lands: a joiner who walked away must
        not hold the host's world in 'verifying' forever."""
        deadline = time.monotonic() + _GATE_TIMEOUT
        while time.monotonic() < deadline:
            time.sleep(1.0)
            p = self._session_get()
            if not p or p.get("room") != room:
                return   # session over or replaced; nothing to guard
            if p.get("state") != "verifying" or p.get("gate_challenge") != challenge:
                return   # answered, or a newer round took over
        p = self._session_get()
        if p and p.get("room") == room and p.get("state") == "verifying":
            self._fail_p2p("No password answer - the world invite timed out.")

    def _on_gate_proof(self, p) -> None:
        """Host: the joiner answered the challenge. Verify; on success hand
        over the connection target, on failure re-challenge (with a fresh
        nonce) until MAX_ATTEMPTS is burned, then close the room."""
        data = p.get("data") or {}
        room = p.get("room")
        pr = self._session_get()
        if not (pr and pr.get("room") == room and pr.get("is_host")
                and pr.get("state") == "verifying"):
            return
        challenge = pr.get("gate_challenge") or ""
        opened = self._open_gate(p, {"kind": "gate_proof", "data": data})
        if opened is None or opened.get("proof_hex") is None:
            return
        if worldgate.verify(challenge, str(opened.get("proof_hex") or "")):
            pr["gate_challenge"] = None
            pr["gate_attempts"] = 0
            pr["gate_authorized"] = True
            # The offer build (STUN + hashing) must leave the dispatch thread.
            threading.Thread(target=self._send_p2p_offer, args=(pr, room),
                             name="p2p-host-offer", daemon=True).start()
            return
        attempts = (pr.get("gate_attempts") or 0) + 1
        pr["gate_attempts"] = attempts
        left = worldgate.MAX_ATTEMPTS - attempts
        if left <= 0:
            self._fail_p2p("Wrong password too many times - the world stays "
                           "closed. Re-invite when you've sorted it out.")
            return
        self._notify(f"Wrong password from your friend - {left} "
                     f"{'try' if left == 1 else 'tries'} left.", error=True)
        # Re-challenge in the gate_fail frame itself: one fresh nonce (and the
        # same salt - it derives from the password, not the round), so the
        # joiner can retype and answer without a second round-trip.
        challenge = worldgate.new_challenge()
        pr["gate_challenge"] = challenge
        record = worldgate.record()
        if not self._send_gate(pr, {
            "kind": "gate_fail", "left": left, "challenge": challenge,
            "salt_hex": record["salt_hex"] if record else "",
            "iterations": record["iterations"] if record
                          else worldgate.PBKDF2_ITERATIONS,
        }):
            return
        self._changed()
        threading.Thread(target=self._gate_challenge_watchdog,
                         args=(room, challenge),
                         name="cubeon-gate-watchdog", daemon=True).start()

    def _send_p2p_offer(self, pr: dict, room: str) -> None:
        """Build the hybrid transport and hand the joiner everything it needs
        (LAN port, STUN candidate, relay session token).

        Runs on a worker thread ON PURPOSE: STUN can block for seconds per
        server, build_mod_list() hashes every enabled jar, and
        build_asset_manifest() hashes up to 128 MB of resourcepacks/configs.
        Doing that inline on the WebSocket dispatch thread would freeze
        presence and heartbeats for every friend for the whole handshake.
        Only ever reached past the worldgate (or with no gate armed)."""

        def prepare_offer():
            session = None
            try:
                if not self._transport_allowed(pr):
                    raise p2p.P2PError("The world password was never verified")

                def _bound(payload):
                    self.client.signal(room, pr["peer"], payload)

                session = p2p.HybridSession(is_host=True, lan_port=pr["lan_port"],
                                            send_signal=_bound)
                pr["punch"] = session
                # Relay pipe FIRST (strategy step 1): guaranteed connectivity
                # before any NAT work, so the joiner can enter the world while
                # punching is still running.
                session.begin()
                self._watch_p2p_transport(session, room)
                pr["_nat_probe"] = None
                try:
                    probe = p2p.probe_nat(session.udp_socket)
                    pr["_nat_probe"] = {
                        "candidate": {"ip": probe["ip"], "port": probe["port"]},
                        "symmetric": probe["symmetric"],
                        "delta": probe["delta"],
                        "probes": probe["probes"],
                    }
                    candidate = {"ip": probe["ip"], "port": probe["port"]}
                except p2p.P2PError:
                    # No STUN reachable: the relay still works - we just can't
                    # punch. The joiner draws the same conclusion from our
                    # missing nat_info.
                    candidate = None
                self.client.signal(room, pr["peer"], {
                    "kind": "p2p_offer", "lan_port": pr["lan_port"],
                    "mc_version": pr["mc_version"], "loader": pr["loader"],
                    "stun_candidate": candidate,
                    "nat_info": pr["_nat_probe"],
                    "transport": p2p.HYBRID_TRANSPORT_TAG,
                    "session_token": session.session_token.hex(),
                    # Capability flag for older builds: they may fall back to
                    # the plain signalling-relay dialect and we will follow them
                    # there (see _run_host_punch / _on_signal).
                    "relay": True,
                })
                pr["net_ready"] = True   # relay pipe is up by construction
                pr["state"] = "connected"
                self._changed()
                # Mod list is its own signal (see p2p.py's module docstring on
                # why) - sent right after the offer, not blocking it.
                mod_list = p2p.build_mod_list(pr["mc_version"], pr["loader"])
                self.client.signal(room, pr["peer"], {
                    "kind": "p2p_modlist", "mc_version": pr["mc_version"],
                    "loader": pr["loader"], "mods": mod_list,
                })
                asset_manifest = p2p.build_asset_manifest()
                self.client.signal(room, pr["peer"], {
                    "kind": "p2p_assetlist", "assets": asset_manifest,
                })
                # Coordinated punching starts once the joiner's answer (carrying
                # ITS nat diagnostics) arrives - see _run_host_punch. A punch
                # that never lands is no longer a failure: the session simply
                # stays on the relay.
            except Exception as e:
                log.debug("p2p offer build failed", exc_info=True)
                if session is not None:
                    try:
                        session.close()
                    except Exception:
                        pass
                    if pr.get("punch") is session:
                        pr["punch"] = None
                if room:
                    try:
                        self.client.call_end(room)
                    except Exception:
                        pass
                self._set_failed(
                    pr, f"Couldn't prepare your world for your friend: {e}")

        threading.Thread(target=prepare_offer, name="p2p-host-offer",
                         daemon=True).start()

    def _on_call_decline(self, p) -> None:
        room = p.get("room")
        # Whatever else happens, this room is dead: forget any invite pointing
        # at it so join() can't be offered a room nobody is holding open.
        if room:
            self._forget_pending(room=room)
        if self._sync_room_closed(p):
            return
        pr = self._session_get()
        if pr and pr.get("room") == room:
            self._notify(f"{self.peer_label(pr.get('peer'))} declined.", error=True)
            if pr.get("punch"):
                pr["punch"].close()
            if not pr.get("is_host") and room:
                p2p.teardown(room)
            self._session_set(None)
        self._changed()

    def _sync_room_closed(self, p) -> bool:
        """True if this CALL_END/CALL_DECLINE was about a sync or askjoin room,
        in which case it has been handled here and the P2P teardown below must
        not run.

        Without this, the Worker's "X is offline." CALL_END (sent when we invite
        someone who just went offline) was silently dropped - it only ever
        reached the player if a world session happened to hold the same room -
        so a compare against a friend who closed the game looked like a hang
        until the 20-second timeout.
        """
        room = p.get("room")
        if not room:
            return False
        canon = self._sync_rooms.pop(room, None)
        if canon is None:
            return False
        rep = self._sync_get(canon)
        message = self._relay_notice(p, canon) if p.get("message") else ""
        if rep and rep.get("_room") in (room, None):
            self._sync_fail(canon, message or f"{self.peer_label(rep['friend'])} closed the "
                                              f"connection.")
        elif message:
            self._notify(message, error=True)
            self._changed()
        return True

    def _on_call_end(self, p) -> None:
        room = p.get("room")
        # Prune first and unconditionally: a host who invited us and then
        # cancelled before we hit Join used to leave a dead room id in the
        # pending map forever, and join() would happily try it.
        if room:
            self._forget_pending(room=room)
        if self._sync_room_closed(p):
            return
        pr = self._session_get()
        # The Worker's "X is offline." reply echoes a relay-allocated room the
        # host never learned (no accept echo came back), so a strict room match
        # would strand a ringing_out host forever. Peer hangups never carry
        # reason:"offline", so this only fires on the server's own reply.
        if (pr and room and pr.get("room") != room
                and p.get("reason") == "offline"
                and pr.get("is_host") and pr.get("state") == "ringing_out"
                and pr.get("room") is None
                and pr.get("peer") == p.get("to")):
            pr["room"] = room
        if pr and (not room or pr.get("room") == room):
            self._cancel_syncs(pr)
            if p.get("message"):
                self._notify(self._relay_notice(p, pr.get("peer")), error=True)
            if pr.get("punch"):
                pr["punch"].close()
            # pr["room"] can be None (host cancelled during hosting_wait_port,
            # before an invite ever went out) - teardown(None) would raise.
            if not pr.get("is_host") and pr.get("room"):
                p2p.teardown(pr["room"])
            # The world password is a per-session secret: gone the moment the
            # session is, whatever side we were.
            worldgate.clear()
            self._session_set(None)
        self._changed()

    def _on_signal(self, p) -> None:
        """The whole P2P signalling router. Every branch re-checks the room
        against the live session before acting, because the session may have
        been replaced or cleared since this frame was queued."""
        data = p.get("data") or {}
        kind = data.get("kind")
        # Profile sync FIRST, before anything looks at the live session. A sync
        # room is not a P2P room, and the HybridSession consumption below keys
        # only on the room id - so a compare that happened to run while a world
        # session was up would otherwise be swallowed by the transport.
        if kind == "cubeon_sync":
            self._on_sync_signal(p, data)
            return
        # Relay-carried CUBP frames + punch coordination for the hybrid session
        # (Relayed Signalling with Direct Hole-Punch Handover). Consumed kinds
        # return; anything else falls through to the mod-sync / legacy handlers
        # below.
        pr0 = self._session_get()
        sess0 = pr0.get("punch") if pr0 else None
        if isinstance(sess0, p2p.HybridSession) and p.get("room") == pr0.get("room"):
            if sess0.on_signal_data(data):
                return

        if kind == "gate_proof":
            # Host: the joiner's password answer (see _on_gate_proof).
            pr = self._session_get()
            if (pr and pr.get("is_host") and p.get("room") == pr.get("room")
                    and pr.get("state") == "verifying"
                    and self._open_gate(pr, p) is not None):
                self._on_gate_proof(p)
            return

        if kind == "gate_challenge":
            # Joiner: the host's world is password-gated. Park the challenge
            # on the session; if the player already typed a password (an
            # earlier round, or typing while the challenge was in flight),
            # answer immediately - otherwise flip to password_needed so the
            # mod shows the password box.
            pr = self._session_get()
            if not pr or pr.get("is_host") or p.get("room") != pr.get("room"):
                return
            opened = self._open_gate(pr, p)
            if opened is None:
                self._fail_p2p("Couldn't securely check the world password. Reopen both launchers and try again.", pr)
                return
            pr["gate_challenge"] = str(opened.get("challenge") or "")
            pr["gate_salt"] = str(opened.get("salt_hex") or "")
            try:
                pr["gate_iters"] = int(opened.get("iterations")
                                       or worldgate.PBKDF2_ITERATIONS)
            except (TypeError, ValueError):
                pr["gate_iters"] = worldgate.PBKDF2_ITERATIONS
            if pr.get("gate_password"):
                self._answer_gate_challenge(pr)
            else:
                pr["state"] = "password_needed"
                self._notify(f"{self.peer_label(pr.get('peer'))}'s world needs a password.")
                self._changed()
            return

        if kind == "gate_ok":
            # Joiner: the host accepted the proof. The p2p_offer follows as
            # its own signal - nothing to do here beyond clearing the round.
            pr = self._session_get()
            if not pr or pr.get("is_host") or p.get("room") != pr.get("room"):
                return
            if self._open_gate(pr, p) is None:
                return
            pr["gate_challenge"] = None
            pr["gate_salt"] = None
            self._changed()
            return

        if kind == "gate_fail":
            # Joiner: wrong proof. The frame carries the fresh nonce (and the
            # same salt) for the next round; put the box back up.
            pr = self._session_get()
            if not pr or pr.get("is_host") or p.get("room") != pr.get("room"):
                return
            opened = self._open_gate(pr, p)
            if opened is None:
                return
            pr["gate_challenge"] = str(opened.get("challenge") or "")
            pr["gate_salt"] = str(opened.get("salt_hex") or "")
            try:
                pr["gate_iters"] = int(opened.get("iterations")
                                       or worldgate.PBKDF2_ITERATIONS)
            except (TypeError, ValueError):
                pr["gate_iters"] = worldgate.PBKDF2_ITERATIONS
            try:
                left = int(opened.get("left"))
            except (TypeError, ValueError):
                left = 0
            pr["gate_password"] = None
            pr["state"] = "password_needed"
            self._notify("Wrong password."
                         + (f" {left} {'try' if left == 1 else 'tries'} left."
                            if left > 0 else ""), error=True)
            self._changed()
            return

        if kind == "p2p_offer":
            # Arrives on the joiner right after they accept - this is what
            # promotes a plain call_invite room into a recognised P2P session
            # (see _on_call_invite's note on ambiguity). If the friend hasn't
            # hit Join yet, just light up their row instead of forcing them in.
            room = p.get("room")
            conv = friends.canonical_name(p.get("from", "")) or (p.get("from") or "").lower()
            pr = self._session_get()
            if pr and pr.get("room") == room and not pr.get("is_host"):
                pr["mc_version"] = data.get("mc_version")
                pr["loader"] = data.get("loader")
                self._run_joiner_punch(data)
            else:
                self._remember_pending(conv, room)
                self._changed()
            return

        if kind == "p2p_answer":
            pr = self._session_get()
            if not (pr and pr.get("is_host") and p.get("room") == pr.get("room")
                    and (friends.canonical_name(p.get("from", ""))
                         or (p.get("from") or "").lower())
                    == (friends.canonical_name(pr.get("peer") or "")
                        or (pr.get("peer") or "").lower())
                    and pr.get("state") in ("verifying", "connected")
                    and pr.get("punch") is not None):
                return
            self._run_host_punch(data)
            return

        if kind == "p2p_use_relay":
            # Peer couldn't punch - switch BOTH sides to the signalling relay.
            # Idempotent: whichever side notices first also switches itself via
            # _switch_to_relay.
            pr = self._session_get()
            if not pr or p.get("room") != pr.get("room"):
                return
            self._switch_to_relay(
                reason="direct connection failed on your friend's side")
            return

        if kind == "p2p_use_minekube":
            # The host's punch failed and their Minekube public server is up -
            # join that directly instead of playing on the relay.
            pr = self._session_get()
            if not pr or pr.get("is_host") or p.get("room") != pr.get("room") \
                    or pr.get("minekube_active"):
                return
            address = (data.get("address") or "").strip()
            if not address:
                return
            pr["minekube_active"] = True
            pr["minekube_address"] = address
            pr["net_ready"] = True  # ready by construction: a normal server join
            if pr.get("punch"):
                pr["punch"].close()
                pr["punch"] = None
            self._notify(f"P2P connection failed. It's on Minekube now. "
                         f"Joining {address}...")
            # State stays "connecting" so the existing mods-ready gating drives
            # the launch (_maybe_finish_join branches on minekube_active).
            self._changed()
            self._maybe_finish_join()
            return

        if kind == "p2p_relay_chunk":
            pr = self._session_get()
            rs = pr.get("punch") if pr else None
            if isinstance(rs, p2p.RelaySession) and p.get("room") == pr.get("room"):
                rs.on_relay_chunk(data)
            return

        if kind == "p2p_modlist":
            # Joiner side: start diffing against our own mods for the same
            # profile as soon as the host's list arrives - runs in parallel with
            # the punch (roadmap Phase 2b), not gated on it.
            pr = self._session_get()
            if not pr or pr.get("is_host") or p.get("room") != pr.get("room"):
                return
            mc_version = data.get("mc_version") or pr.get("mc_version")
            loader = data.get("loader") or pr.get("loader")
            core = _core()
            selected_version = self.state.get("selected_version")
            selected_mc = core.extract_mc_version(selected_version) if selected_version else None
            selected_loader = self.state.get("mod_loader")
            # Pre-flight: refuse rather than link a 1.21 host's mods into a
            # 1.20 profile and let Minecraft explode on launch.
            if selected_mc and selected_loader and \
                    (selected_mc != mc_version or selected_loader != loader):
                self._fail_p2p(
                    f"Your Play profile is {selected_mc} / {selected_loader}, but "
                    f"the host is running {mc_version} / {loader}. Select the "
                    f"matching profile before joining."
                )
                return
            if not mc_version or not loader:
                self._fail_p2p("Your friend's world didn't report a Minecraft "
                               "version/loader - can't sync mods safely.")
                return

            def _send(payload):
                self.client.signal(pr["room"], pr["peer"], payload)

            def _sync_error(message):
                self._record_links(pr, mc_version, loader)
                self._fail_p2p(message, pr)

            sync = p2p.ModSyncSession(mc_version=mc_version, loader=loader,
                                      send_signal=_send, on_error=_sync_error)
            sync.journal = lambda: self._record_links(pr, mc_version, loader)
            pr["mod_sync"] = sync

            def worker():
                sync.start(data.get("mods") or [])
                if sync.error:
                    self._record_links(pr, mc_version, loader)
                    self._fail_p2p(sync.error)
                    return
                if sync.is_complete():
                    self._record_links(pr, mc_version, loader)
                    pr["mods_ready"] = True
                    self._maybe_finish_join()
                # else: still waiting on p2p_modchunk signals - the branch below
                # finishes the job and calls _maybe_finish_join itself.

            threading.Thread(target=worker, name="p2p-mod-sync-start",
                             daemon=True).start()
            return

        if kind == "p2p_assetlist":
            pr = self._session_get()
            if not pr or pr.get("is_host") or p.get("room") != pr.get("room"):
                return

            def _send_asset(payload):
                self.client.signal(pr["room"], pr["peer"], payload)

            def _asset_error(message):
                self._record_links(pr, pr.get("mc_version"), pr.get("loader"))
                self._fail_p2p(message, pr)

            sync = p2p.AssetSyncSession(send_signal=_send_asset,
                                        on_error=_asset_error)
            sync.journal = lambda: self._record_links(pr, pr.get("mc_version"),
                                                      pr.get("loader"))
            pr["asset_sync"] = sync

            def asset_worker():
                sync.start(data.get("assets") or [])
                if sync.error:
                    self._record_links(pr, pr.get("mc_version"), pr.get("loader"))
                    self._fail_p2p(sync.error)
                    return
                if sync.is_complete():
                    self._record_links(pr, pr.get("mc_version"), pr.get("loader"))
                    pr["assets_ready"] = True
                    self._maybe_finish_join()

            threading.Thread(target=asset_worker,
                             name="cubeon-p2p-asset-sync-start", daemon=True).start()
            return

        if kind == "p2p_assetreq":
            pr = self._session_get()
            if not pr or not pr.get("is_host") or p.get("room") != pr.get("room"):
                return
            asset_kind, rel = data.get("asset_kind"), data.get("path")

            def asset_serve():
                try:
                    target = p2p._asset_target(asset_kind, rel)
                    if p2p.hash_file(target) != str(data.get("sha256") or "").lower():
                        return
                    chunks = p2p.read_chunks_for_asset(target)
                    for seq, chunk in enumerate(chunks):
                        self.client.signal(pr["room"], pr["peer"], {
                            "kind": "p2p_assetchunk", "asset_kind": asset_kind,
                            "path": rel, "seq": seq, "total": len(chunks),
                            "data_b64": chunk,
                        })
                except Exception:
                    pass  # best-effort; an unanswered request just times out

            threading.Thread(target=asset_serve, name="cubeon-p2p-asset-serve",
                             daemon=True).start()
            return

        if kind == "p2p_assetchunk":
            pr = self._session_get()
            if not pr or pr.get("is_host") or not pr.get("asset_sync") \
                    or p.get("room") != pr.get("room"):
                return
            sync = pr["asset_sync"]
            sync.on_chunk(data)
            if sync.error:
                self._record_links(pr, pr.get("mc_version"), pr.get("loader"))
                self._fail_p2p(sync.error)
            elif sync.is_complete():
                self._record_links(pr, pr.get("mc_version"), pr.get("loader"))
                pr["assets_ready"] = True
                self._maybe_finish_join()
            return

        if kind == "p2p_modreq":
            # Host side: a joiner is asking for a mod by hash. Look it up in our
            # own active profile (the same one build_mod_list() just advertised)
            # and stream it back in chunks. Silent no-op if we somehow don't
            # have it - the joiner's session will just time out waiting rather
            # than get a confusing partial answer.
            pr = self._session_get()
            if not pr or not pr.get("is_host") or p.get("room") != pr.get("room"):
                return
            sha = (data.get("sha256") or "").lower()

            def worker():
                try:
                    core = _core()
                    profile_dir = core.get_profile_dir(pr["mc_version"], pr["loader"])
                    match = None
                    for entry in core.list_mods(pr["mc_version"], pr["loader"]):
                        if not entry["enabled"]:
                            continue
                        full = os.path.join(profile_dir, entry["filename"])
                        if os.path.isfile(full) and p2p.hash_file(full) == sha:
                            match = full
                            break
                    if not match:
                        return
                    chunks = p2p.read_chunks_for_mod(match)
                    for seq, chunk in enumerate(chunks):
                        self.client.signal(pr["room"], pr["peer"], {
                            "kind": "p2p_modchunk", "sha256": sha,
                            "seq": seq, "total": len(chunks), "data_b64": chunk,
                        })
                except Exception:
                    pass  # best-effort - a failed send just leaves the joiner's
                    # request unanswered/timed out

            threading.Thread(target=worker, name="p2p-mod-serve", daemon=True).start()
            return

        if kind == "p2p_modchunk":
            pr = self._session_get()
            if not pr or pr.get("is_host") or not pr.get("mod_sync") \
                    or p.get("room") != pr.get("room"):
                return
            sync = pr["mod_sync"]
            sync.on_modchunk(data)
            if sync.error:
                self._fail_p2p(sync.error)
            elif sync.is_complete():
                self._record_links(pr, pr.get("mc_version"), pr.get("loader"))
                pr["mods_ready"] = True
                self._maybe_finish_join()
            return

        # Anything else is opaque voice-transport negotiation - hand straight to
        # the audio layer if it's running; a no-op otherwise. Nothing else
        # routes unrecognised signal frames, so this fallthrough must stay.
        try:
            from cubeon import voice
            voice.on_signal(p)
        except Exception:
            pass


def _local_skin_name(cfg: dict) -> str:
    """The skin on record for THIS machine's account, as a display name.

    Prefers what CustomSkinLoader is actually serving (the LocalSkin mirror
    written by skins.sync_local_skin_to_csl), falls back to the launcher's
    active-skin choice, "" when neither exists - the mod renders "default".
    """
    try:
        from .paths import CSL_LOCAL_SKINS_DIR
        username = (cfg.get("username") or "").strip()
        if username and os.path.isfile(
                os.path.join(CSL_LOCAL_SKINS_DIR, f"{username}.png")):
            return f"{cfg.get('active_skin') or 'custom'} (local)"
    except Exception:
        pass
    return cfg.get("active_skin") or ""


def _local_cape_name(cfg: dict) -> str:
    """The cape on record for THIS machine's account, same rules as the skin."""
    try:
        from .paths import CSL_LOCAL_CAPES_DIR
        username = (cfg.get("username") or "").strip()
        if username and os.path.isfile(
                os.path.join(CSL_LOCAL_CAPES_DIR, f"{username}.png")):
            return f"{cfg.get('active_cape') or 'custom'} (local)"
    except Exception:
        pass
    return cfg.get("active_cape") or ""


def _mod_stamp(version_id) -> str:
    """The jar freshness fingerprint, lazily imported: friends_service runs in
    the launcher, cubeonfriends knows which jar it would inject. Failure or no
    jar just means no fingerprint, and the mod skips the check."""
    try:
        from . import cubeonfriends
        return cubeonfriends.mod_stamp(version_id)
    except Exception:
        log.debug("mod_stamp lookup failed", exc_info=True)
        return ""
