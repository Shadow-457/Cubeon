"""
Friends - the social layer: a unique Cubeon name, a friends list, presence
(online/offline + which Minecraft version they're in), direct and group chat,
and the signalling half of voice calls.

WHY A "CUBEON NAME" AND NOT JUST THE USERNAME

Offline/cracked accounts have no identity - anyone can set their in-game
username to "Notch", which is exactly why skin uploads are still blocked
(nothing can answer "who may write this username's skin?"). A friends list
keyed on an impersonable name is worthless: you'd never know who you actually
added.

So Cubeon mints a *separate* identity - a Cubeon name - owned by a capability
secret, the same trick `invites.py` uses for invite codes. A freshly claimed
name has no rightful owner to impersonate, so ownership is *created* at claim
time: the launcher generates a 256-bit secret, the server stores only its
SHA-256, and every later connection must present the same secret. No signup, no
email, nothing to phish, and a database dump leaks nothing replayable. The name
is public (you give it to friends); the secret never leaves this machine, which
is why identity.json is 0600 - lose it and you re-claim a name, leak it and
someone can log in as you.

WHY A DURABLE OBJECT AND NOT KV

Presence and chat are realtime, and KV's free tier allows ~1000 writes/day
*total across every Cubeon user*. A single 30-second presence heartbeat is 2880
writes/day on its own - it would exhaust the budget for everyone before lunch.
So the realtime layer is a Cloudflare Durable Object holding live WebSocket
connections; its own storage isn't metered like KV writes. KV is not used here
at all. See worker/cubeon-friends.js.

WHAT THIS MODULE IS

The client half. Three separable pieces, in dependency order:

  1. Name format + validation - pure, offline, testable with no network.
  2. The identity file - this machine's claimed name and its owning secret.
  3. The network client - a synchronous HTTP claim/lookup, plus a threaded
     WebSocket client (`FriendsClient`) that carries presence, chat, and
     voice-call signalling.

The actual voice *audio* (mic capture, playback) lives in cubeon/voice.py behind
an optional dependency, so the base launcher install stays light. This module
only relays the call signalling messages, which are plain JSON.

Every network call returns a result dict and raises nothing the caller has to
handle - these run from UI click handlers on background threads, where an
escaped exception is a silent dead button. Callers check `ok` and show
`message`, which is already a finished human sentence. This is the same contract
as invites.py.
"""
import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time

# Lazy: `requests` costs ~97ms to import and every module that pulls it in
# eagerly puts that on the startup path, even for a session that never
# touches the network. Call sites are unchanged - see cubeon/lazy.py.
from .lazy import LazyModule
requests = LazyModule("requests")

from .config import ensure_auth_key, stable_secret, stable_uuid
from .paths import CUBEON_HOME

log = logging.getLogger(__name__)

# This machine's claimed name and the secret that owns it. Local only - the
# authoritative name registry lives in the Durable Object. Holds the one
# genuinely sensitive value Cubeon stores (the identity secret), hence 0600,
# exactly like invites.json.
IDENTITY_PATH = os.path.join(CUBEON_HOME, "identity.json")

# Prefix for the automatic Cubeon name every install gets without ever being
# asked. The handle is derived from the machine's stable secret (auth_key.json)
# rather than typed, so first run needs no claim prompt and two installs can't
# pick the same name by accident. "Player_" is deliberately NOT the brand name:
# the reserved-name list exists to stop anyone impersonating "Cubeon"/"admin",
# and a name that *starts* with the brand would invite exactly that confusion.
AUTO_NAME_PREFIX = "Player_"

# Width of the secret-derived discriminator appended to a *chosen* name
# ("Dragon" -> "Dragon4821"). Four decimal digits is the familiar Discord-style
# shape; it is seeded by the same stable secret, so a given machine always
# renders the same number for a given base.
AUTO_NAME_DIGITS = 4

# Last roster the server sent us, cached so the Friends tab can paint instantly
# on launch instead of showing an empty list until the WebSocket connects. Not
# sensitive (no secrets, just names/status), so no 0600 and a corrupt file just
# means a blank first paint.
ROSTER_CACHE_PATH = os.path.join(CUBEON_HOME, "friends_cache.json")

# Deployed. Mirrors the skins/invites Worker naming (same account); deploy steps
# live in worker/README.md. Overridable via env so it can point at
# `wrangler dev` without editing shipped code.
DEFAULT_API_ROOT = "https://cubeon-friends.hamza-457-shahbaz.workers.dev"

# Short timeouts: claim/lookup sit between a click and visible feedback, so a
# hung request must fail fast enough for the UI to say so rather than look dead.
TIMEOUT = (5, 10)  # (connect, read)

# The budget for a lookup that sits *inside* another action rather than being
# the action - e.g. the pubkey fetch send_chat() needs before it can encrypt.
# The in-game mod gives one action 30s end to end, and a caller that spends
# TIMEOUT's worst case (15s) on a sub-lookup has already burned half of it, so
# these get their own, tighter budget.
FAST_TIMEOUT = (3, 4)  # (connect, read)


# ---------------------------------------------------------------------------
# Message protocol.
#
# Every WebSocket frame is a JSON object with a "t" (type) field. These
# constants are the single source of truth on the client; the Worker mirrors
# the exact strings, and tools/test_friends.py reads the Worker source and
# asserts parity - a silent divergence would only surface in production, the
# same failure mode the invite CODE_RE parity test guards against.
# ---------------------------------------------------------------------------

# Client -> server.
T_HELLO = "hello"            # {name, secret, version, status} - first frame, authenticates
T_ADD = "add"                # {name} or {uid} - send a friend request
T_REMOVE = "remove"          # {name} - drop a friend (both directions)
T_ACCEPT = "accept"          # {name} - accept an incoming request
T_DECLINE = "decline"        # {name} - reject an incoming request
T_DM = "dm"                  # {to, text, id} - direct message
T_GROUP_NEW = "group_new"    # {name, members:[...]} - create a group
T_GROUP_MSG = "group_msg"    # {gid, text, id} - message a group
T_GROUP_LEAVE = "group_leave"  # {gid}
T_VERSION = "version"        # {version} - "now playing <version>", or null when stopped
T_STATUS = "status"          # {status} - "online" | "away" | "playing"
T_HISTORY = "history"        # {peer} or {gid} - ask for recent messages
T_TYPING = "typing"          # {to} or {gid} - "I'm typing in this conversation right now"
T_CALL_INVITE = "call_invite"  # {to} - ring a friend
T_CALL_ACCEPT = "call_accept"  # {room} - pick up
T_CALL_DECLINE = "call_decline"  # {room}
T_CALL_END = "call_end"      # {room} - hang up / leave the call
T_SIGNAL = "signal"          # {room, to, data} - opaque voice-transport signalling, relayed as-is

# Server -> client.
T_HELLO_OK = "hello_ok"      # {name, uuid} - authenticated; a roster frame follows
T_ERROR = "error"            # {code, message} - a claim/hello/action was refused
T_ROSTER = "roster"          # {friends, requests_in, requests_out, groups} - full state on connect
T_PRESENCE = "presence"      # {name, online, status, version} - one friend changed
T_REQUEST = "request"        # {from} - someone added you
T_FRIEND_ADDED = "friend_added"  # {name} - your request was accepted
T_FRIEND_REMOVED = "friend_removed"  # {name}
T_GROUP_CREATED = "group_created"  # {gid, name, members}
T_GROUP_UPDATE = "group_update"    # {gid, name, members}
T_SYSTEM = "system"          # {text} - a server-side notice to show in a thread
# T_DM / T_GROUP_MSG / T_CALL_* / T_SIGNAL are echoed back with the same type,
# with {from, ts} added, so the client dispatches incoming and outgoing chat
# through one code path.


# ---------------------------------------------------------------------------
# 1. Name format + validation. Pure and offline.
# ---------------------------------------------------------------------------

# A Cubeon name is what friends type to add you and what shows in chat. Same
# character rules as a Minecraft username (letters, digits, underscore, 3-16)
# so it reads as a game handle and can default to the user's existing username,
# but uniqueness is enforced server-side where a username's isn't.
_NAME_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")

# The public numeric ID, assigned by the server on first registration: twelve
# zero-padded decimal digits, starting at 000000000001. This is what the Chat
# surface shows and what a friend types to add you - a name and a secret are no
# longer how chat identity works. Must equal the worker's UID_RE / UID_WIDTH.
_UID_RE = re.compile(r"^[0-9]{12}$")
UID_WIDTH = 12

# Reserved so nobody can claim a name that impersonates the system or the app
# itself in a chat list ("Cubeon: your account is locked, send your secret...").
_RESERVED = {"cubeon", "admin", "system", "server", "moderator", "mod", "staff"}


def canonical_uid(uid: "str | int | None") -> "str | None":
    """The canonical 12-digit form of a Cubeon ID, or None if it isn't one.

    Accepts an int or a string; a bare number is zero-padded to 12 digits so the
    value a user pastes and the value the server returns compare equal.
    """
    if isinstance(uid, bool):
        return None
    if isinstance(uid, int):
        if uid < 0:
            return None
        # A bare number arrives zero-padded: 1 -> "000000000001". Strings are
        # NOT padded ("42" stays rejected) so a typo can't silently match a
        # different user's ID.
        uid = str(uid).zfill(UID_WIDTH)
    if not isinstance(uid, str):
        return None
    uid = uid.strip()
    if not _UID_RE.match(uid):
        return None
    return uid


def format_uid(uid: "str | int | None") -> str:
    """A best-effort display form: zero-padded to 12 digits, or "" when the
    value isn't numeric enough to format."""
    canon = canonical_uid(uid)
    if canon:
        return canon
    try:
        return str(int(str(uid).strip())).zfill(UID_WIDTH)
    except (TypeError, ValueError):
        return ""



def validate_name(name: str) -> "tuple[bool, str]":
    """(ok, error) for a proposed Cubeon name. The error is a finished sentence."""
    if not isinstance(name, str) or not name:
        return False, "Pick a Cubeon name."
    if not (3 <= len(name) <= 16):
        return False, "Name must be 3-16 characters."
    if not _NAME_RE.match(name):
        return False, "Only letters, numbers, and underscores allowed."
    if name.lower() in _RESERVED:
        return False, "That name is reserved. Pick another."
    return True, ""


def canonical_name(name: str) -> "str | None":
    """The comparison form: lower-cased, or None if the name is invalid.

    Uniqueness and lookups are case-insensitive (so "BlueFox" and "bluefox" are
    the same account) but the original casing is preserved for display. The
    Worker lower-cases identically - this is the client half of that contract.
    """
    if not isinstance(name, str) or not _NAME_RE.match(name):
        return None
    return name.lower()


def generate_secret() -> str:
    """The capability that owns a Cubeon name. 256 bits, url-safe so it survives
    an HTTP header and a WebSocket URL untouched. Never shown, never shared."""
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# 2. The identity file: this machine's claimed name + owning secret.
#
# A flat json file rewritten whole, 0600. Losing it is survivable (claim a new
# name); leaking it lets someone log in as you, which is why it's the one
# friends file worth protecting.
# ---------------------------------------------------------------------------

def load_identity() -> "dict | None":
    """This machine's identity, or None if no name has been claimed yet."""
    try:
        with open(IDENTITY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("name") or not data.get("secret"):
        return None
    return data


def save_identity(name: str, secret: "str | None" = None,
                  uid: "str | None" = None) -> dict:
    """Persists the claimed name + owning secret with 0600, atomically. Returns
    the stored identity dict (including the stable identity uuid, so callers
    don't recompute it).

    The secret defaults to this machine's stable secret (auth_key.json) - the
    claimed name is just a public handle over that one durable account, so the
    same secret owns every name this machine ever claims. An explicit secret can
    still be passed (used by tests). The uuid stored is always the stable v4
    identity uuid, NOT offline_uuid(name): that's what makes the account survive
    a rename - see config.ensure_auth_key().

    `uid` is the server-assigned 12-digit public ID. It is preserved across a
    rename via the prior-fields merge below when not passed, and set when a
    claim/hello_ok hands back a fresh one."""
    os.makedirs(CUBEON_HOME, exist_ok=True)
    if secret is None:
        secret = stable_secret()
    identity = {"name": name, "secret": secret, "uuid": stable_uuid()}
    canon_uid = canonical_uid(uid)
    if canon_uid:
        identity["uid"] = canon_uid
    # Preserve fields that other features have parked in identity.json (e.g. the
    # E2EE key in "e2ee_sk"): a rename re-claims the same machine and must not
    # silently rotate its encryption identity. name/secret/uuid above always win.
    try:
        with open(IDENTITY_PATH, "r", encoding="utf-8") as f:
            prior = json.load(f)
        if isinstance(prior, dict):
            for key, value in prior.items():
                identity.setdefault(key, value)
    except (OSError, json.JSONDecodeError):
        pass
    tmp = IDENTITY_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(identity, f, indent=2)
        # Tightened before the rename so the secret is never briefly world-
        # readable under the final name. Best-effort - Windows/odd filesystems
        # may no-op, and that must not break claiming.
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, IDENTITY_PATH)  # atomic; a crash can't truncate it
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return identity


def clear_identity() -> None:
    """Forgets the local identity (a "sign out" / "switch name"). The name stays
    claimed server-side - only re-presenting the secret proves ownership - so
    this is deliberately non-destructive to the registry."""
    try:
        os.remove(IDENTITY_PATH)
    except OSError:
        pass


def current_name() -> "str | None":
    identity = load_identity()
    return identity.get("name") if identity else None


def current_uid() -> str:
    """This machine's 12-digit Cubeon ID, or "" before the server has assigned
    one (first connection). Safe to call anywhere - never raises."""
    identity = load_identity()
    if not identity:
        return ""
    return canonical_uid(identity.get("uid")) or ""


def remember_uid(uid: "str | None") -> bool:
    """Persists a server-assigned ID onto the existing identity. True if it
    changed the file. A no-op without an identity, an invalid ID, or when the
    ID already matches, so it is safe to call on every hello_ok."""
    canon = canonical_uid(uid)
    identity = load_identity()
    if not canon or not identity:
        return False
    if canonical_uid(identity.get("uid")) == canon:
        return False
    save_identity(identity["name"], identity.get("secret"), uid=canon)
    return True


# ---------------------------------------------------------------------------
# 2b. Automatic identity - the user never types or claims a Cubeon name.
#
# A Cubeon name is only meaningful when it is *owned*; ownership comes from the
# stable secret in auth_key.json, not from the string. So the name itself is
# presentation, and an install can mint a perfectly good one from that secret
# instead of interrupting first-run with a claim dialog. The derivation is
# deterministic: the same auth_key.json always yields the same handle, and a
# fresh install's 256-bit secret makes a collision with another machine's
# handle effectively impossible. The server binds "claim-on-connect" (see
# worker/cubeon-friends.js onHello), so saving the derived identity locally is
# enough - the first WebSocket hello registers it, and the claim is idempotent
# if it ever replays. Rename stays available for users who want a chosen name.
# ---------------------------------------------------------------------------

def auto_name() -> str:
    """The deterministic Cubeon handle for this machine's stable secret.

    "Player_" + the first 8 hex of SHA-256(secret): 15 chars, inside the
    3-16 name limit, and made only of the allowed [A-Za-z0-9_] set. Never
    looks like a reserved/system name, and never changes for a given
    auth_key.json, so a friend who added you once keeps working across
    launcher reinstalls as long as the key survives."""
    digest = hashlib.sha256(stable_secret().encode("utf-8")).hexdigest()
    return AUTO_NAME_PREFIX + digest[:8]


def ensure_identity() -> dict:
    """This machine's identity, minting the automatic one when none exists.

    Returns the existing identity untouched when a name has already been
    claimed (auto or user-renamed), so this is safe to call on every startup -
    it can never silently rotate a name a friend already knows. Only a truly
    nameless install gets the derived handle, which is written to disk
    immediately so presence can connect even while offline."""
    identity = load_identity()
    if identity and identity.get("name"):
        return identity
    return save_identity(auto_name())


def unique_number(attempt: int = 0) -> str:
    """The secret-derived discriminator, zero-padded to AUTO_NAME_DIGITS.

    Deterministic for a given auth_key.json. `attempt` walks to a different
    number when a chosen base actually collides with another machine, so the
    number stays secret-seeded while a rare clash can still resolve."""
    digest = hashlib.sha256(stable_secret().encode("utf-8")).hexdigest()
    modulus = 10 ** AUTO_NAME_DIGITS
    return str((int(digest, 16) + int(attempt)) % modulus).zfill(AUTO_NAME_DIGITS)


def unique_name(base: str, attempt: int = 0) -> str:
    """A chosen display name made unique with the secret discriminator.

    "Dragon" -> "Dragon4821". The base is reduced to name-safe characters and
    stripped of any trailing digits first, so re-applying the result is
    idempotent instead of stacking a second number ("Dragon4821" -> "Dragon4821",
    not "Dragon48214821"). Truncated to leave room for the discriminator, and
    guaranteed to be a valid, non-reserved name - a reserved word only ever
    appears as a prefix, never as the whole handle."""
    base = re.sub(r"[^A-Za-z0-9_]", "", (base or "").strip())
    base = base.rstrip("0123456789") or AUTO_NAME_PREFIX.rstrip("_")
    number = unique_number(attempt)
    base = base[:16 - len(number)] or "P"
    return base + number


def name_base(name: str) -> str:
    """The editable stem of a generated handle: everything before the trailing
    discriminator, so a rename field can prefill with "Dragon" for the current
    "Dragon4821". The untouched auto handle ("Player_<8hex>") yields the bare
    "Player" rather than the hash, which reads like a name instead of a key.
    A name that is all digits is returned unchanged."""
    text = (name or "").strip()
    if text.startswith(AUTO_NAME_PREFIX):
        rest = text[len(AUTO_NAME_PREFIX):]
        if len(rest) == 8 and all(c in "0123456789abcdef" for c in rest.lower()):
            return AUTO_NAME_PREFIX.rstrip("_")
    return text.rstrip("0123456789") or text


# ---------------------------------------------------------------------------
# Roster cache - a non-sensitive snapshot for an instant first paint.
# ---------------------------------------------------------------------------

def load_cached_roster() -> dict:
    try:
        with open(ROSTER_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"friends": [], "requests_in": [], "requests_out": [], "groups": []}


def save_cached_roster(roster: dict) -> None:
    try:
        os.makedirs(CUBEON_HOME, exist_ok=True)
        with open(ROSTER_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(roster, f)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# 3a. Synchronous HTTP: claim a name, check a name exists.
#
# These are one-shot request/response and don't need the WebSocket. Claiming in
# particular wants immediate yes/no feedback in the dialog, before any realtime
# connection is attempted.
# ---------------------------------------------------------------------------

_MESSAGES = {
    "name_taken": "That Cubeon name is already taken. Try another.",
    "bad_name": "That name isn't allowed. Use 3-16 letters, numbers, or underscores.",
    "bad_uid": "That doesn't look like a Cubeon ID. It's 12 numbers.",
    "not_yours": "That name belongs to another computer.",
    "bad_body": "Cubeon and the friends server disagreed about the request format.",
    "blocked": "This name was blocked for breaking the rules.",
}
_OFFLINE = ("Couldn't reach the Cubeon friends server. Check your internet and "
            "try again.")


def _api_root(base_url: "str | None" = None) -> str:
    return (base_url
            or os.environ.get("CUBEON_FRIENDS_API")
            or DEFAULT_API_ROOT).rstrip("/")


def _ws_url(base_url: "str | None" = None) -> str:
    """The WebSocket endpoint derived from the HTTP root: https->wss, http->ws."""
    root = _api_root(base_url)
    if root.startswith("https://"):
        return "wss://" + root[len("https://"):] + "/ws"
    if root.startswith("http://"):
        return "ws://" + root[len("http://"):] + "/ws"
    return root + "/ws"


def _fail(error: str, message: "str | None" = None, **extra) -> dict:
    return {"ok": False, "error": error,
            "message": message or _MESSAGES.get(error, _OFFLINE), **extra}


def _from_response(resp) -> dict:
    try:
        error = (resp.json() or {}).get("error") or f"http_{resp.status_code}"
    except ValueError:
        error = f"http_{resp.status_code}"
    return _fail(error, status=resp.status_code)


def claim(name: str, *, base_url: "str | None" = None) -> dict:
    """Claims a Cubeon name for this machine, or re-confirms one it already owns.

    Idempotent: calling it with a name this machine already holds (same secret)
    succeeds and is how the name is re-verified. Calling it with a name someone
    else holds returns `name_taken`. On success the identity is written to disk
    *before* returning, so the owning secret survives a crash right after.
    """
    ok, err = validate_name(name)
    if not ok:
        return _fail("bad_name", err)

    # The owning secret and the account uuid both come from the stable identity
    # (auth_key.json), not from the name. So every name this machine claims is
    # owned by the same durable account, and re-claiming always proves ownership
    # by re-presenting that same secret instead of minting a new one.
    identity_key = ensure_auth_key()
    secret = identity_key["secret_token"]

    try:
        resp = requests.post(
            f"{_api_root(base_url)}/claim",
            json={"name": name, "secret": secret, "uuid": identity_key["public_uuid"]},
            timeout=TIMEOUT,
        )
    except requests.RequestException as ex:
        log.warning("name claim failed: %s", ex.__class__.__name__)
        return _fail("offline", _OFFLINE)

    if resp.status_code != 200:
        return _from_response(resp)

    try:
        body = resp.json() or {}
    except ValueError:
        body = {}
    identity = save_identity(name, secret, uid=body.get("uid"))
    return {"ok": True, "name": name, "uuid": identity["uuid"],
            "uid": current_uid()}


def check_name(name: str, *, base_url: "str | None" = None) -> dict:
    """Looks up whether a name exists (so 'add friend' can reject a typo before
    sending a request nobody will ever see). Returns ok=True with exists/online."""
    canon = canonical_name(name)
    if not canon:
        return _fail("bad_name", "That doesn't look like a Cubeon name.")
    try:
        resp = requests.get(f"{_api_root(base_url)}/name/{canon}", timeout=TIMEOUT)
    except requests.RequestException as ex:
        log.warning("name lookup failed: %s", ex.__class__.__name__)
        return _fail("offline", _OFFLINE)
    if resp.status_code == 404:
        return {"ok": True, "exists": False, "online": False}
    if resp.status_code != 200:
        return _from_response(resp)
    try:
        body = resp.json()
    except ValueError:
        return _fail("bad_response", _OFFLINE)
    return {"ok": True, "exists": True, "online": bool(body.get("online"))}


def lookup_uid(uid: "str | int", *, base_url: "str | None" = None) -> dict:
    """Resolves a 12-digit Cubeon ID to the account behind it, so the Chat tab
    can reject a typo'd ID and show the friend's name. Returns ok=True with
    exists/name/online; exists=False when no account holds that ID."""
    canon = canonical_uid(uid)
    if not canon:
        return _fail("bad_uid", _MESSAGES["bad_uid"])
    try:
        resp = requests.get(f"{_api_root(base_url)}/uid/{canon}", timeout=TIMEOUT)
    except requests.RequestException as ex:
        log.warning("uid lookup failed: %s", ex.__class__.__name__)
        return _fail("offline", _OFFLINE)
    if resp.status_code == 404:
        return {"ok": True, "exists": False, "name": "", "online": False,
                "uid": canon}
    if resp.status_code != 200:
        return _from_response(resp)
    try:
        body = resp.json()
    except ValueError:
        return _fail("bad_response", _OFFLINE)
    return {"ok": True, "exists": True, "uid": canon,
            "name": body.get("name") or "",
            "online": bool(body.get("online"))}


def publish_pubkey(pubkey_b64: str, *, base_url: "str | None" = None) -> dict:
    """Advertises this machine's E2EE public key under its claimed name, so
    friends can write it encrypted DMs. Authenticated exactly like a claim:
    the owning secret proves the caller is the account's holder.

    The key is base64 and opaque to the server - the relay stores and serves
    it so it can relay DMs it can never read (see cubeon/e2ee.py)."""
    pubkey_b64 = (pubkey_b64 or "").strip()
    if not pubkey_b64:
        return _fail("bad_body", "No public key to publish.")
    identity = load_identity()
    if not identity:
        return _fail("no_identity", "Claim a Cubeon name before enabling encrypted chat.")
    try:
        resp = requests.post(
            f"{_api_root(base_url)}/pubkey",
            json={"name": identity["name"], "secret": identity["secret"],
                  "pubkey": pubkey_b64},
            timeout=TIMEOUT,
        )
    except requests.RequestException as ex:
        log.warning("pubkey publish failed: %s", ex.__class__.__name__)
        return _fail("offline", _OFFLINE)
    if resp.status_code != 200:
        return _from_response(resp)
    return {"ok": True, "name": identity["name"]}


def fetch_pubkey(name: str, *, base_url: "str | None" = None,
                 timeout=None) -> dict:
    """The E2EE public key a friend advertises, needed to send them an
    encrypted DM. ok=True with pubkey=="" when the name exists but has never
    published a key; ok=True with exists=False when the name doesn't exist.

    `timeout` overrides the module default - pass FAST_TIMEOUT when this lookup
    is a step inside a bigger action that a UI is already waiting on."""
    canon = canonical_name(name)
    if not canon:
        return _fail("bad_name", "That doesn't look like a Cubeon name.")
    try:
        resp = requests.get(f"{_api_root(base_url)}/pubkey/{canon}",
                            timeout=timeout or TIMEOUT)
    except requests.RequestException as ex:
        log.warning("pubkey lookup failed: %s", ex.__class__.__name__)
        return _fail("offline", _OFFLINE)
    if resp.status_code == 404:
        return {"ok": True, "exists": False, "pubkey": ""}
    if resp.status_code != 200:
        return _from_response(resp)
    try:
        body = resp.json()
    except ValueError:
        return _fail("bad_response", _OFFLINE)
    return {"ok": True, "exists": True, "pubkey": str(body.get("pubkey") or "")}


# ---------------------------------------------------------------------------
# 3b. The realtime client.
#
# A background-thread WebSocket that carries everything live: presence, chat,
# group updates, and voice-call signalling. Modelled on the rest of the
# launcher's threading - slow/blocking work off the UI thread, results delivered
# via callbacks, and page.update() made safe from any thread by
# cubeon/thread_safe_ui.py.
#
# The class never raises into its callers. connect()/send are safe to call
# before, during, or after a connection; anything that can't happen yet is
# dropped or deferred rather than thrown.
# ---------------------------------------------------------------------------

try:
    import websocket  # from the `websocket-client` package
    _HAVE_WS = True
except Exception:  # pragma: no cover - exercised only on a broken install
    websocket = None
    _HAVE_WS = False


# Reconnect backoff: quick first retries so a blip is invisible, then capped so
# a server that's truly down isn't hammered. Presence/chat tolerate a short gap.
_RECONNECT_BACKOFF = [1, 2, 5, 10, 20, 30]


class FriendsClient:
    """A single live connection to the friends hub.

    Usage: create one, register callbacks (or pass them via `on`), call
    connect(). All `on_*` callbacks fire on the WebSocket thread - they mutate
    Flet controls and call page.update(), which is thread-safe here (see
    thread_safe_ui). Keep them short; do slow work elsewhere.
    """

    def __init__(self, *, base_url: "str | None" = None):
        self._base_url = base_url
        self._ws = None
        self._thread = None
        self._send_lock = threading.Lock()
        self._stop = threading.Event()
        self._connected = threading.Event()
        self._identity = None
        # What we announce on (re)connect, so a reconnect restores the same
        # presence the user last set without the UI having to re-push it.
        self._version = None
        self._status = "online"
        # Last full roster the server sent, kept so the UI can re-read current
        # state after it rebuilds (e.g. switching to the Friends tab) without a
        # round-trip. Seeded from the on-disk cache for an instant first paint.
        self.roster = load_cached_roster()
        # Milestones: seed the friend-count high-water mark (Party hat) from
        # the cached roster so a user who hit 3 friends yesterday sees the
        # hat on next launch, not after the next roster frame. _connect()
        # will re-feed the live count anyway. Cosmetic - guarded.
        try:
            from . import milestones as _milestones
            _milestones.note_friends_count(len(self.roster["friends"]))
        except Exception:
            pass
        # Callbacks. Default to no-ops so the client works headless (e.g. tests)
        # and so a missing handler is never an AttributeError on the WS thread.
        self._handlers = {}

    # -- configuration ------------------------------------------------------

    def on(self, event: str, fn) -> None:
        """Register a handler. Events mirror the server message types without the
        T_ prefix: 'roster', 'presence', 'dm', 'group_msg', 'request',
        'friend_added', 'friend_removed', 'group_created', 'group_update',
        'system', 'error', 'call_invite', 'call_accept', 'call_decline',
        'call_end', 'signal', 'typing', plus 'state' (connected/disconnected)."""
        self._handlers[event] = fn

    def _emit(self, event: str, payload=None) -> None:
        fn = self._handlers.get(event)
        if fn is None:
            return
        try:
            fn(payload)
        except Exception:
            # A UI callback that throws must not kill the receive loop and take
            # the whole connection down with it.
            log.exception("friends: handler for %r failed", event)

    # -- lifecycle ----------------------------------------------------------

    @property
    def is_available(self) -> bool:
        """False if the websocket-client dependency is missing - the Friends tab
        checks this to explain the problem instead of silently doing nothing."""
        return _HAVE_WS

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    def connect(self, identity: "dict | None" = None) -> bool:
        """Starts (or restarts) the background connection. Returns False if there's
        no identity to connect with or the WS dependency is missing - both are
        states the UI surfaces, not errors to raise."""
        if not _HAVE_WS:
            log.warning("friends: websocket-client not installed; realtime disabled")
            return False
        identity = identity or load_identity()
        if not identity:
            return False
        self._identity = identity
        # Restarting: stop the old loop first so we never run two.
        if self._thread and self._thread.is_alive():
            self.disconnect()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True,
                                        name="cubeon-friends-ws")
        self._thread.start()
        return True

    def disconnect(self) -> None:
        self._stop.set()
        self._connected.clear()
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    def _run_loop(self) -> None:
        """Connect, run until closed, reconnect with backoff, until stopped."""
        attempt = 0
        while not self._stop.is_set():
            try:
                self._ws = websocket.WebSocketApp(
                    _ws_url(self._base_url),
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                # ping_interval keeps the connection alive through Cloudflare's
                # idle-timeout without any application-level heartbeat (which
                # would be pointless writes); it's a protocol ping, not a message.
                self._ws.run_forever(ping_interval=25, ping_timeout=10)
            except Exception as ex:
                log.warning("friends ws loop error: %s", ex.__class__.__name__)
            self._connected.clear()
            if self._stop.is_set():
                break
            delay = _RECONNECT_BACKOFF[min(attempt, len(_RECONNECT_BACKOFF) - 1)]
            attempt += 1
            self._emit("state", {"connected": False, "retry_in": delay})
            # Interruptible sleep so disconnect() doesn't wait out the backoff.
            self._stop.wait(delay)
        self._emit("state", {"connected": False, "retry_in": None})

    # -- receive ------------------------------------------------------------

    def _on_open(self, ws) -> None:
        # Authenticate as the very first frame, over the already-encrypted
        # socket - the secret goes here, never in the URL, so it can't leak into
        # Cloudflare's request logs. The server replies hello_ok or error.
        self._raw_send({
            "t": T_HELLO,
            "name": self._identity["name"],
            "secret": self._identity["secret"],
            "uuid": self._identity.get("uuid"),
            "version": self._version,
            "status": self._status,
        })

    def _on_message(self, ws, raw) -> None:
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            return
        if not isinstance(msg, dict):
            return
        t = msg.get("t")

        if t == T_HELLO_OK:
            self._connected.set()
            # The server hands back the account's 12-digit ID on every hello.
            # Persist it here so the Chat surface can show it without a separate
            # REST round trip, and so it survives even if /claim was never
            # called (claim-on-connect).
            try:
                if remember_uid(msg.get("uid")):
                    self._emit("identity", {"uid": current_uid()})
            except Exception:
                log.debug("couldn't persist the server-assigned uid", exc_info=True)
            self._emit("state", {"connected": True, "retry_in": None})
            self._emit("hello_ok", msg)
            return
        if t == T_ROSTER:
            self.roster = {
                "friends": msg.get("friends", []),
                "requests_in": msg.get("requests_in", []),
                "requests_out": msg.get("requests_out", []),
                "groups": msg.get("groups", []),
            }
            save_cached_roster(self.roster)
            # Milestones: friend-count high-water mark for the Party hat.
            # The roster is the single authoritative update point, so the
            # feed lives here rather than in every consumer. Cosmetic -
            # guarded so a milestone failure can never break presence.
            try:
                from . import milestones as _milestones
                _milestones.note_friends_count(len(self.roster["friends"]))
            except Exception:
                pass
            self._emit("roster", self.roster)
            return

        # Everything else maps type -> handler name 1:1. Keeping the map explicit
        # (rather than emitting the raw type) means an unknown/garbage type from
        # a future server is ignored, not dispatched into the UI.
        event = {
            T_PRESENCE: "presence", T_REQUEST: "request",
            T_FRIEND_ADDED: "friend_added", T_FRIEND_REMOVED: "friend_removed",
            T_GROUP_CREATED: "group_created", T_GROUP_UPDATE: "group_update",
            T_SYSTEM: "system", T_ERROR: "error",
            T_DM: "dm", T_GROUP_MSG: "group_msg", T_HISTORY: "history",
            T_TYPING: "typing",
            T_CALL_INVITE: "call_invite", T_CALL_ACCEPT: "call_accept",
            T_CALL_DECLINE: "call_decline", T_CALL_END: "call_end",
            T_SIGNAL: "signal",
        }.get(t)
        if event:
            self._emit(event, msg)

    def _on_error(self, ws, error) -> None:
        log.debug("friends ws error: %s", error)

    def _on_close(self, ws, *args) -> None:
        self._connected.clear()
        self._emit("state", {"connected": False, "retry_in": None})

    # -- send ---------------------------------------------------------------

    def _raw_send(self, obj: dict) -> bool:
        """Sends one JSON frame. Returns False (never raises) if the socket isn't
        writable - the caller's action is simply dropped, which for chat/presence
        is preferable to an exception on a background thread."""
        ws = self._ws
        if ws is None:
            return False
        try:
            with self._send_lock:
                ws.send(json.dumps(obj))
            return True
        except Exception:
            return False

    # Convenience senders. Each returns whether the frame went out; the UI can
    # optimistically render its own message either way, since the server echoes
    # accepted messages back with a timestamp.

    def add_friend(self, name: str) -> bool:
        return self._raw_send({"t": T_ADD, "name": name})

    def add_friend_uid(self, uid: "str | int") -> bool:
        """Send a friend request by 12-digit ID. The server resolves it to the
        account and, exactly like add_friend(), turns a mutual add into an
        accept. Returns whether the frame went out - never raises."""
        canon = canonical_uid(uid)
        if not canon:
            return False
        return self._raw_send({"t": T_ADD, "uid": canon})

    def remove_friend(self, name: str) -> bool:
        return self._raw_send({"t": T_REMOVE, "name": name})

    def accept_request(self, name: str) -> bool:
        return self._raw_send({"t": T_ACCEPT, "name": name})

    def decline_request(self, name: str) -> bool:
        return self._raw_send({"t": T_DECLINE, "name": name})

    def check_name(self, name: str) -> dict:
        """REST read (not a WS frame): does this name exist on the server this
        client talks to? Returns friends.check_name()'s dict, so the caller can
        tell "exists" from "the lookup itself failed" instead of guessing."""
        return check_name(name, base_url=self._base_url)

    def check_uid(self, uid: "str | int") -> dict:
        """REST read: resolve a 12-digit ID to its name/presence, or report
        exists=False. Same contract as check_name() - the caller can tell a
        missing account from a failed lookup."""
        return lookup_uid(uid, base_url=self._base_url)

    def publish_pubkey(self, pubkey_b64: str) -> dict:
        """Publishes this name's E2EE public key so friends can write it
        encrypted DMs. REST, authenticated by the owning secret - see
        friends.publish_pubkey()."""
        return publish_pubkey(pubkey_b64, base_url=self._base_url)

    def fetch_pubkey(self, name: str, *, timeout=None) -> dict:
        """A friend's advertised E2EE public key. Returns the module-level
        dict (ok/exists/pubkey) so the caller can tell "no such friend" from
        "friend hasn't set up encrypted chat yet". `timeout` is forwarded, so a
        caller inside another action can cap how long it waits."""
        return fetch_pubkey(name, base_url=self._base_url, timeout=timeout)

    def send_dm(self, to: str, text: str, msg_id: "str | None" = None) -> bool:
        return self._raw_send({"t": T_DM, "to": to, "text": text,
                               "id": msg_id or secrets.token_hex(8)})

    def create_group(self, name: str, members: "list[str]") -> bool:
        return self._raw_send({"t": T_GROUP_NEW, "name": name, "members": members})

    def send_group(self, gid: str, text: str, msg_id: "str | None" = None) -> bool:
        return self._raw_send({"t": T_GROUP_MSG, "gid": gid, "text": text,
                               "id": msg_id or secrets.token_hex(8)})

    def leave_group(self, gid: str) -> bool:
        return self._raw_send({"t": T_GROUP_LEAVE, "gid": gid})

    def request_history(self, *, peer: "str | None" = None,
                        gid: "str | None" = None) -> bool:
        payload = {"t": T_HISTORY}
        if peer:
            payload["peer"] = peer
        if gid:
            payload["gid"] = gid
        return self._raw_send(payload)

    def send_typing(self, *, peer: "str | None" = None, gid: "str | None" = None) -> bool:
        """Tells the other side (or group) 'I'm typing right now'. Fire-and-
        forget like call signalling - dropped silently if the socket isn't
        up, since a missed typing ping is never worth surfacing an error
        for. The UI is expected to call this at most a few times a second
        (e.g. throttled on keystroke), not on every single character."""
        payload = {"t": T_TYPING}
        if peer:
            payload["to"] = peer
        if gid:
            payload["gid"] = gid
        return self._raw_send(payload)

    def set_version(self, version: "str | None") -> None:
        """Announce the Minecraft version this user is now in (None when they
        stop). Cached so a reconnect restores it, and pushed live if connected -
        this is what powers 'BlueFox is playing 1.20.1' in a friend's list."""
        self._version = version
        self._status = "playing" if version else "online"
        self._raw_send({"t": T_VERSION, "version": version})
        self._raw_send({"t": T_STATUS, "status": self._status})

    def set_status(self, status: str) -> None:
        self._status = status
        self._raw_send({"t": T_STATUS, "status": status})

    # -- voice-call signalling ---------------------------------------------
    # These only relay JSON. The audio transport (cubeon/voice.py) rides the
    # 'signal' messages; if the voice add-on isn't installed the call still
    # rings and connects as signalling, it just carries no audio.

    def call_invite(self, to: str, *, kind: str | None = None) -> bool:
        """Ring a friend for a voice or another room-based feature.

        ``kind`` is optional for backwards compatibility. The server simply
        relays it with the invite, so the receiver can decide whether the
        incoming room belongs to voice or a feature such as P2P worlds before
        accepting it.
        """
        payload = {"t": T_CALL_INVITE, "to": to}
        if kind:
            payload["kind"] = kind
        return self._raw_send(payload)

    def call_accept(self, room: str) -> bool:
        return self._raw_send({"t": T_CALL_ACCEPT, "room": room})

    def call_decline(self, room: str) -> bool:
        return self._raw_send({"t": T_CALL_DECLINE, "room": room})

    def call_end(self, room: str) -> bool:
        return self._raw_send({"t": T_CALL_END, "room": room})

    def signal(self, room: str, to: str, data: dict) -> bool:
        return self._raw_send({"t": T_SIGNAL, "room": room, "to": to, "data": data})
