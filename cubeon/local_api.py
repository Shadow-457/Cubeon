"""
Local bridge between the Cubeon launcher and the in-game "Cubeon Friends" mod.

The mod (see the mod/ project) adds a Friends button to Minecraft's own game
menu - and since the launcher no longer has a Friends tab, that button is now
the only Friends UI there is. The mod can't reach the friends backend directly
(that lives in the launcher's process), so the launcher exposes this tiny HTTP
API on 127.0.0.1 and the mod talks to it. The bridge is deliberately thin: it
only EXPOSES what cubeon/friends_service.py already knows (the roster, the P2P
session state, a queue of notifications) and FORWARDS what the player clicks
straight into that service. No backend logic lives here.

Auth: the server binds to 127.0.0.1 with a random port and a random token
written to ~/.cubeon_launcher/local_api.json (0600). The mod reads the same
file. Requests without the token are refused - other local processes (other
users) can't drive your friends list.

Everything is fail-safe: if this server can't start (port blocked, firewall),
the game simply doesn't show the Friends button - the launcher is unaffected.
"""

import json
import hmac
import logging
import os
import secrets
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .paths import CUBEON_HOME  # ~/.cubeon_launcher

_TOKEN_FILE = os.path.join(CUBEON_HOME, "local_api.json")
# A POST body is small JSON (the largest is a base64 E2EE DM envelope). Anything
# bigger is refused instead of being truncated into unparseable JSON.
_MAX_BODY_BYTES = 16384

log = logging.getLogger(__name__)

# Handlers cubeon/friends_service.py registers on startup. Everything that takes
# a name takes the raw string the player typed; the service validates it and
# returns the error text, because the wording belongs with the rules.
#   roster_provider()   -> {"you", "connected", "available", "friends": [...],
#                           "requests_in": [...], "requests_out": [...]}
#   status_provider()   -> {"state","peer","error","is_host","quality",
#                           "can_retry"} or {} when there is no session
#   events_provider(since) -> {"cursor": int, "events": [{seq,text,error}, ...]}
#   invite_handler(name)   -> host a P2P world for that friend
#   join_handler(name)     -> accept their invite and join
#   cancel_handler()       -> end the active session
#   retry_handler()        -> retry a failed session
#   add/accept/decline/remove_handler(name), whitelist_handler(name, on),
#   rename_handler(name)   -> all {"ok": bool, "error": str}
#   dm_handler(to, text)   -> {"ok": bool, "error": str}. POST /dm - send an
#                             E2EE-encrypted DM; encrypts, so it can block.
#   chat_provider(friend, after) -> {"friend","you","messages":[...]}. GET
#                             /chat transcript polling.
#   sync_provider(friend)  -> the profile-compare report. GET /sync?friend=
#   syncstart/syncdownload/syncclose_handler(name), askjoin_handler(name)
_providers = {
    "roster": None,
    "invite": None,
    "status": None,
    "events": None,
    "cancel": None,
    "retry": None,
    "join": None,
    "add": None,
    "accept": None,
    "decline": None,
    "remove": None,
    "whitelist": None,
    "rename": None,
    "dm": None,
    "chat": None,
    "sync": None,
    "syncstart": None,
    "syncdownload": None,
    "syncclose": None,
    "askjoin": None,
    "players": None,
    # Worldgate: the host's optional LAN-world password (POST /worldgate) and
    # the joiner's answer to a challenge (POST /joinpassword). See
    # cubeon/worldgate.py for the protocol.
    "worldgate": None,
    "joinpassword": None,
}

# POST routes that take a single {"name": ...} and return a result dict. Keeping
# them in one table means adding a friend-scoped action is a one-line change and
# they can't drift apart in their error handling.
_NAME_ROUTES = ("add", "accept", "decline", "remove", "rename", "join",
                "syncstart", "syncdownload", "syncclose", "askjoin")

# POST routes that take no arguments at all.
_BARE_ROUTES = ("cancel", "retry")
def set_invite_handler(fn) -> None:
    """fn(name) -> {"ok": bool, "error": str}. Hosts a P2P world for a friend."""
    _providers["invite"] = fn


def set_join_handler(fn) -> None:
    """fn(name) -> {"ok": bool, "error": str}. Joins a friend's P2P world."""
    _providers["join"] = fn


def set_status_provider(fn) -> None:
    _providers["status"] = fn


def set_events_provider(fn) -> None:
    """fn(since:int) -> {"cursor": int, "events": [...]}. since<0 means "first
    sync, skip the backlog" - a mod that just started shouldn't replay old news."""
    _providers["events"] = fn


def set_cancel_handler(fn) -> None:
    _providers["cancel"] = fn


def set_retry_handler(fn) -> None:
    _providers["retry"] = fn


def set_worldgate_handler(fn) -> None:
    _providers["worldgate"] = fn


def set_joinpassword_handler(fn) -> None:
    _providers["joinpassword"] = fn


def set_roster_provider(fn) -> None:
    _providers["roster"] = fn


def set_add_handler(fn) -> None:
    """fn(name) -> {"ok": bool, "error": str|None}. Sends a friend request."""
    _providers["add"] = fn


def set_accept_handler(fn) -> None:
    """fn(name) -> {"ok": bool, "error": str|None}. Accepts a request."""
    _providers["accept"] = fn


def set_decline_handler(fn) -> None:
    """fn(name) -> {"ok": bool, "error": str|None}. Declines a request."""
    _providers["decline"] = fn


def set_remove_handler(fn) -> None:
    """fn(name) -> {"ok": bool, "error": str|None}. Unfriends someone."""
    _providers["remove"] = fn


def set_whitelist_handler(fn) -> None:
    """fn(name, on) -> {"ok": bool, "error": str|None}. Adds or removes a friend
    from the installed server's whitelist."""
    _providers["whitelist"] = fn


def set_rename_handler(fn) -> None:
    """fn(name) -> {"ok": bool, "error": str|None, "message": str}. Re-claims
    this machine's Cubeon name (rename). Blocking HTTP claim - run off UI threads."""
    _providers["rename"] = fn


def set_dm_handler(fn) -> None:
    """fn(to, text) -> {"ok": bool, "error": str}. Encrypts and sends one DM.
    Encrypting and the relay round-trip can block, so it must run off UI
    threads (as _call already does for every POST)."""
    _providers["dm"] = fn


def set_chat_provider(fn) -> None:
    """fn(friend, after) -> {"friend","you","messages":[{seq,dir,name,text,ts}]}.
    after=-1 means "most recent page"; after>=0 means "seq > after" ascending."""
    _providers["chat"] = fn


def set_sync_provider(fn) -> None:
    """fn(friend) -> the profile-compare report:
    {"friend","state","error","encrypted","you"{version,loader,mods},"them"{...},
     "version_ok","loader_ok","missing":[{sha256,filename,size}],"extra":[...],
     "can_download","download_done","download_total","needs_relaunch",
     "lines":[...]}. state is idle|asking|ready|downloading|error. Polled, so it
    must not block."""
    _providers["sync"] = fn


def set_sync_start_handler(fn) -> None:
    """fn(name) -> {"ok","error"}. Opens the compare channel to a friend."""
    _providers["syncstart"] = fn


def set_sync_download_handler(fn) -> None:
    """fn(name) -> {"ok","error"}. Pulls the mods this machine is missing."""
    _providers["syncdownload"] = fn


def set_sync_close_handler(fn) -> None:
    """fn(name) -> {"ok","error"}. Drops the compare room."""
    _providers["syncclose"] = fn


def set_askjoin_handler(fn) -> None:
    """fn(name) -> {"ok","error"}. Asks a friend to open their world to us."""
    _providers["askjoin"] = fn


def set_players_provider(fn) -> None:
    """fn() -> {"players": [{"name","online","skin","cape","version","status"}]}.
    GET /players - what the in-game Friends screen's roster reads for
    skin/cape/presence details. Must not block; anything missing
    degrades to "" so the mod renders fewer details, never an error."""
    _providers["players"] = fn


def _write_token(port: int, token: str) -> None:
    os.makedirs(CUBEON_HOME, exist_ok=True)
    # 0600 BEFORE a single byte is written: `open()` used the default mode
    # (typically 0644) until the chmod after os.replace, so for a moment any
    # local user could read the bearer token. mkstemp creates the file 0600 and
    # with a unique name, so a leftover/racing temp is neither reused nor
    # world-readable.
    fd, tmp = tempfile.mkstemp(prefix=".local-api-", suffix=".tmp",
                              dir=os.path.dirname(_TOKEN_FILE) or ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"port": port, "token": token}, f)
        os.replace(tmp, _TOKEN_FILE)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        os.chmod(_TOKEN_FILE, 0o600)
    except OSError:
        pass


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence the default stderr spam
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        provided = self.headers.get("X-Cubeon-Token") or ""
        expected = getattr(self.server, "token", "") or ""
        # Constant-time comparison: the token is a bearer secret, and `==`
        # leaks its prefix timing. Encode so a non-ASCII header cannot raise.
        try:
            return hmac.compare_digest(provided.encode("utf-8"),
                                       expected.encode("utf-8"))
        except (UnicodeEncodeError, TypeError):
            return False

    def do_GET(self):
        if not self._authorized():
            self._json({"error": "unauthorized"}, 401)
            return
        # A provider raising used to kill this request thread with no body at
        # all; the mod reads a null response as "Cubeon launcher isn't
        # running". Answer 500 with the reason instead (do_POST already does
        # the same through _call).
        try:
            self._dispatch_get()
        except Exception as ex:
            log.warning("local API GET %s failed", self.path, exc_info=True)
            try:
                self._json({"error": str(ex)}, 500)
            except Exception:
                pass

    def _dispatch_get(self):
        # /events carries a query string, so route on the path alone.
        parts = urlsplit(self.path)
        if parts.path == "/friends":
            fn = _providers["roster"]
            roster = fn() if fn else {}
            friends = [f for f in (roster.get("friends") or [])
                       if isinstance(f, dict) and f.get("name")]
            requests_in = [r for r in (roster.get("requests_in") or [])
                           if isinstance(r, str) and r]
            requests_out = [r for r in (roster.get("requests_out") or [])
                            if isinstance(r, str) and r]
            # connected/available default to True when the provider doesn't say,
            # matching the mod's own defaults: an older launcher that omits them
            # should read as "working", not as "signed out".
            self._json({"friends": friends,
                        "requests_in": requests_in,
                        "requests_out": requests_out,
                        "connected": bool(roster.get("connected", True)),
                        "available": bool(roster.get("available", True)),
                        "connection": roster.get("connection") or {},
                        "you": roster.get("you") or "",
                        "you_uid": roster.get("you_uid") or "",
                        "you_minecraft_username": roster.get("you_minecraft_username") or "",
                        "you_display_name": roster.get("you_display_name") or "Player",
                        "mod_stamp": roster.get("mod_stamp") or "",
                        "requests_in_details": [r for r in (roster.get("requests_in_details") or [])
                                                if isinstance(r, dict) and r.get("name")],
                        "requests_out_details": [r for r in (roster.get("requests_out_details") or [])
                                                 if isinstance(r, dict) and r.get("name")]})
        elif parts.path == "/status":
            fn = _providers["status"]
            self._json(fn() if fn else {})
        elif parts.path == "/events":
            fn = _providers["events"]
            if not fn:
                self._json({"cursor": 0, "events": []})
                return
            # A missing or unparseable ?since= means "first sync": the provider
            # reads a negative cursor as "give me no backlog".
            try:
                since = int(parse_qs(parts.query).get("since", ["-1"])[0])
            except (TypeError, ValueError):
                since = -1
            try:
                self._json(fn(since))
            except Exception as ex:
                self._json({"cursor": since, "events": [], "error": str(ex)}, 500)
        elif parts.path == "/chat":
            fn = _providers["chat"]
            if not fn:
                self._json({"friend": "", "you": "", "messages": []})
                return
            query = parse_qs(parts.query)
            friend = str(query.get("friend", [""])[0] or "").strip()
            # Missing/unparseable ?after= means "first sync": the provider
            # reads -1 as "give me the most recent page" and seeds history.
            try:
                after = int(query.get("after", ["-1"])[0])
            except (TypeError, ValueError):
                after = -1
            try:
                self._json(fn(friend, after))
            except Exception as ex:
                self._json({"friend": friend, "you": "", "messages": [],
                            "error": str(ex)}, 500)
        elif parts.path == "/players":
            fn = _providers["players"]
            if not fn:
                # An older service (or a plain-bridge launcher): an empty list
                # is the mod's "nothing known" answer, never a 404 crash.
                self._json({"players": []})
                return
            try:
                payload = fn()
            except Exception as ex:
                self._json({"players": [], "error": str(ex)}, 500)
                return
            players = [p for p in (payload.get("players") or [])
                       if isinstance(p, dict) and p.get("name")]
            self._json({"players": players})
        elif parts.path == "/sync":
            fn = _providers["sync"]
            friend = str(parse_qs(parts.query).get("friend", [""])[0] or "").strip()
            if not fn:
                # An older launcher with a newer mod: say "idle" rather than 404
                # so the mod's poll loop treats it as "nothing open", not as a
                # dead bridge.
                self._json({"friend": friend, "state": "idle", "error": "",
                            "lines": [], "missing": [], "extra": []})
                return
            try:
                self._json(fn(friend))
            except Exception as ex:
                self._json({"friend": friend, "state": "error", "error": str(ex),
                            "lines": [str(ex)], "missing": [], "extra": []}, 500)
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if not self._authorized():
            self._json({"error": "unauthorized"}, 401)
            return
        try:
            # Generous cap: DM bodies carry a base64 E2EE envelope, which runs
            # ~1.4x the plaintext length. Still bounded, so a misbehaving mod
            # can't make the launcher buffer an unbounded request.
            declared = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            declared = 0
        if declared > _MAX_BODY_BYTES:
            # Refuse instead of reading a prefix: the truncated JSON used to
            # parse as {} and the action silently did nothing. Read nothing
            # more, so the cap is also a real guard on buffered bytes.
            self._json({"ok": False, "error": "message too large"}, 413)
            return
        try:
            body = json.loads(self.rfile.read(max(0, declared)) or b"{}")
        except (ValueError, json.JSONDecodeError):
            body = {}
        if not isinstance(body, dict):
            body = {}
        route = urlsplit(self.path).path.lstrip("/")

        if route == "invite":
            # Kept separate from the table below: invite takes the name the
            # player picked from their own roster, so an empty one is the
            # service's error to word, not a 400.
            name = str(body.get("name") or "").strip()
            fn = _providers["invite"]
            if not fn:
                self._json({"ok": False, "error": "no invite handler"}, 503)
                return
            self._call(lambda: fn(name))
        elif route == "rename":
            self._json({"ok": False,
                        "error": "Change your Minecraft username in the launcher. Your Cubeon ID stays the same."})
        elif route in _NAME_ROUTES:
            name = str(body.get("name") or "").strip()
            if not name:
                self._json({"ok": False, "error": "missing name"}, 400)
                return
            fn = _providers[route]
            if not fn:
                self._json({"ok": False, "error": "no handler"}, 503)
                return
            self._call(lambda: fn(name))
        elif route == "whitelist":
            name = str(body.get("name") or "").strip()
            if not name:
                self._json({"ok": False, "error": "missing name"}, 400)
                return
            fn = _providers["whitelist"]
            if not fn:
                self._json({"ok": False, "error": "no handler"}, 503)
                return
            on = bool(body.get("on"))
            self._call(lambda: fn(name, on))
        elif route == "worldgate":
            # The host's password decision: {"password": "..."} arms the gate,
            # {"skip": true} (or an empty password) leaves the world open to
            # anyone the invite reaches. Empty-password-as-skip keeps the mod
            # to one button.
            fn = _providers["worldgate"]
            if not fn:
                self._json({"ok": False, "error": "no worldgate handler"}, 503)
                return
            if body.get("skip"):
                self._call(lambda: fn(None))
                return
            self._call(lambda: fn(str(body.get("password") or "")))
        elif route == "joinpassword":
            # The joiner's answer to a gate_challenge. Runs the PBKDF2 proof
            # (a few hundred ms of CPU), so it goes through the same forgiving
            # _call wrapper as everything else.
            fn = _providers["joinpassword"]
            if not fn:
                self._json({"ok": False, "error": "no joinpassword handler"}, 503)
                return
            self._call(lambda: fn(str(body.get("password") or "")))
        elif route == "dm":
            to = str(body.get("to") or "").strip()
            text = str(body.get("text") or "").strip()
            if not to or not text:
                self._json({"ok": False, "error": "missing to or text"}, 400)
                return
            fn = _providers["dm"]
            if not fn:
                self._json({"ok": False, "error": "no handler"}, 503)
                return
            self._call(lambda: fn(to, text))
        elif route in _BARE_ROUTES:
            fn = _providers[route]
            if not fn:
                # Nothing to cancel is not a failure; nothing to retry is.
                self._json({"ok": route == "cancel",
                            "error": "" if route == "cancel" else "no handler"})
                return
            self._call(fn)
        else:
            self._json({"error": "not found"}, 404)

    def _call(self, thunk):
        """Run a handler and answer with its result dict.

        Handlers are trusted to be quick - they hand slow work to a worker
        thread - but never to be exception-free: an unhandled one here would
        otherwise close the socket with no body and the mod would report
        "launcher not responding" for what is really one failed action.
        """
        try:
            result = thunk()
        except Exception as ex:
            self._json({"ok": False, "error": str(ex)}, 500)
            return
        if isinstance(result, dict):
            self._json(result)
        else:
            self._json({"ok": bool(result) or result is None, "error": ""})


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def start() -> bool:
    """Starts the bridge on a random 127.0.0.1 port and writes the token file
    the mod reads. Returns True if it's up (or already up)."""
    if getattr(start, "_server", None) is not None:
        return True
    try:
        server = _Server(("127.0.0.1", 0), _Handler)
        token = secrets.token_urlsafe(24)
        server.token = token
        thread = threading.Thread(target=server.serve_forever, daemon=True,
                                  name="cubeon-local-api")
        thread.start()
        _write_token(server.server_address[1], token)
        start._server = server
        return True
    except Exception:
        return False


def stop() -> None:
    server = getattr(start, "_server", None)
    if server is None:
        return
    try:
        server.shutdown()
    except Exception:
        pass
    start._server = None
    # Another launcher may have started (or a fast restart already rewrote the
    # file) while this one was shutting down. Deleting its token would leave
    # that process's in-game mod unable to connect until the next restart, so
    # only remove the file while it still holds OUR token.
    try:
        with open(_TOKEN_FILE, "r", encoding="utf-8") as fh:
            recorded = json.load(fh).get("token")
    except (OSError, ValueError, AttributeError):
        return
    try:
        ours = recorded is not None and hmac.compare_digest(
            str(recorded).encode("utf-8"),
            str(getattr(server, "token", "")).encode("utf-8"))
    except (UnicodeEncodeError, TypeError):
        ours = False
    if not ours:
        return
    try:
        os.remove(_TOKEN_FILE)
    except OSError:
        pass
