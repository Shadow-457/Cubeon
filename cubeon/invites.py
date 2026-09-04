"""
Invite codes - turning a tunnel address into something a kid can type.

WHY THIS EXISTS

A tunnel address looks like `my-server.play.minekube.net` (Minekube
Connect). That is fine to paste into Discord and hopeless to say out loud,
and "send a link" is the whole product pitch. So Cubeon mints a short code -
`CUBE-7F4K-9QMN` - that maps to whatever the real address turns out to be.

The indirection is worth more than the shortening:

  * The provider becomes swappable. Minekube today, UPnP or a VPS later, and
    the code the host already shared keeps working, because only the mapping's
    value changes.
  * The address can change without re-sharing. A tunnel endpoint can be
    renamed or reassigned; a friend group that saved the code doesn't care.
  * It hides the provider from players entirely, so nobody has to be told what
    the tunnel service is.

WHAT THIS MODULE DOES

Three separable things, in this order:

  1. The code format - generating and canonicalizing codes. Pure, offline,
     testable with no account and no network.
  2. The local record - which codes this machine minted or joined, and the
     secret that proves ownership of each minted one.
  3. The network client - publishing a code's current address to the Worker so
     a friend on another machine can resolve it, and resolving one.

The split matters because (1) and (2) are where the fiddly human-facing bugs
live (a typo'd code, a lost secret) and they can be tested exhaustively without
touching a network. See `worker/cubeon-invites.js` for the server side.

OWNERSHIP WITHOUT ACCOUNTS

Cracked accounts have no identity, which is why skin uploads are still blocked:
nothing can answer "who may write this username's skin?" Invite codes dodge
that because a fresh code has no rightful owner to impersonate - ownership can
be *created* at claim time rather than proven. The launcher generates a 256-bit
secret, the Worker stores only its hash, and later writes must present the same
secret. No signup, nothing to phish.

That makes the secret the one genuinely sensitive thing in `invites.json`: lose
it and the host can never repoint their code again (they mint a new one and
re-share it); leak it and someone else can. Hence 0600 on the file.

ALPHABET CHOICE

Codes get read aloud, typed on phones, and screenshotted, so the alphabet drops
every character pair that survives none of that: 0/O, 1/I/L, 2/Z, 5/S, 8/B. What
remains is 25 characters, unambiguous when spoken and when read in most fonts.
Two groups of four gives 25^8 ≈ 152 billion codes - far past any collision
concern at Cubeon's scale, while staying short enough to say in one breath.

Codes are also case-insensitive and punctuation-insensitive on input: a kid
typing `cube7f4k9qmn` or `CUBE 7F4K 9QMN` gets the same result as the canonical
`CUBE-7F4K-9QMN`. Rejecting a correct code over a missing dash is the kind of
small cruelty that makes software feel broken.
"""
import json
import logging
import os
import re
import secrets
import time

import requests

from .paths import CUBEON_HOME

log = logging.getLogger(__name__)

# Where this machine's own minted/joined codes are remembered. Local only - the
# authoritative mapping lives server-side, this is for showing the host their
# code again after a restart without a network round-trip.
INVITES_PATH = os.path.join(CUBEON_HOME, "invites.json")

# Unambiguous when spoken and when read: no 0/O, 1/I/L, 2/Z, 5/S, 8/B.
ALPHABET = "34679ACDEFGHJKMNPQRTUVWXY"

PREFIX = "CUBE"
GROUP_LEN = 4
GROUPS = 2

# Canonical form is what we display and store: CUBE-XXXX-XXXX.
_CANONICAL_RE = re.compile(
    rf"^{PREFIX}-[{ALPHABET}]{{{GROUP_LEN}}}-[{ALPHABET}]{{{GROUP_LEN}}}$"
)


def generate() -> str:
    """A fresh invite code in canonical form.

    Uses `secrets`, not `random`: a guessable code is a stranger joining a
    child's private server. 152 billion possibilities only helps if they can't
    be predicted from each other.
    """
    groups = [
        "".join(secrets.choice(ALPHABET) for _ in range(GROUP_LEN))
        for _ in range(GROUPS)
    ]
    return "-".join([PREFIX, *groups])


def generate_secret() -> str:
    """The capability that proves ownership of a code.

    256 bits, url-safe so it survives an HTTP header untouched. This is the only
    thing standing between a host's friends and someone repointing their code,
    and unlike the code itself it is never shown or shared.
    """
    return secrets.token_urlsafe(32)


def normalize(text: str) -> str | None:
    """Canonicalizes user-typed input, or None if it isn't a valid code.

    Accepts lowercase, missing or extra dashes, spaces, and a pasted
    `cubeon.run.place/CUBE-...`-style URL tail, because all of those are what
    actually arrives when a code travels through Discord and back. Returns the
    canonical `CUBE-XXXX-XXXX` so callers only ever compare one form.
    """
    if not isinstance(text, str):
        return None

    # Keep only characters that can appear in a code, uppercased. This drops
    # dashes, spaces, URL fragments, and invisible characters pasted from chat.
    cleaned = re.sub(r"[^A-Za-z0-9]", "", text).upper()

    # A pasted URL leaves the host in front of the code. The code is the tail,
    # so take the last PREFIX-marked run if one exists.
    idx = cleaned.rfind(PREFIX)
    if idx > 0:
        cleaned = cleaned[idx:]

    if not cleaned.startswith(PREFIX):
        # Tolerate a code shared without its prefix (people do strip it).
        if len(cleaned) == GROUP_LEN * GROUPS:
            cleaned = PREFIX + cleaned
        else:
            return None

    body = cleaned[len(PREFIX):]
    if len(body) != GROUP_LEN * GROUPS:
        return None
    if any(c not in ALPHABET for c in body):
        # A likely-looking typo (O for 0, l for 1) lands here rather than
        # silently resolving to someone else's server.
        return None

    groups = [body[i:i + GROUP_LEN] for i in range(0, len(body), GROUP_LEN)]
    return "-".join([PREFIX, *groups])


def is_valid(text: str) -> bool:
    """True if text is a well-formed code in any accepted spelling."""
    return normalize(text) is not None


def is_canonical(text: str) -> bool:
    """True only for the exact display form, CUBE-XXXX-XXXX."""
    return bool(isinstance(text, str) and _CANONICAL_RE.match(text))


# --------------------------------------------------------------------------
# Local record of codes this machine has minted or joined.
#
# Deliberately dumb: a flat json file, rewritten whole. It holds tens of
# entries at most.
#
# It does hold each minted code's secret, though, which makes it the one
# Cubeon file with something worth protecting in it - hence 0600. Losing it is
# survivable (mint a new code, re-share it); leaking it lets someone else
# repoint a code the host's friends already trust.
# --------------------------------------------------------------------------

def _load() -> dict:
    try:
        with open(INVITES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"hosted": {}, "joined": {}}
    # Tolerate a hand-edited or half-written file rather than raising into a UI
    # callback: a broken invites.json must never stop the launcher starting.
    if not isinstance(data, dict):
        return {"hosted": {}, "joined": {}}
    for key in ("hosted", "joined"):
        if not isinstance(data.get(key), dict):
            data[key] = {}
    return data


def _save(data: dict) -> None:
    os.makedirs(CUBEON_HOME, exist_ok=True)
    tmp = INVITES_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        # Tightened before the rename, so the secrets are never briefly readable
        # under the final name. Best-effort: no-ops meaningfully on Windows, and
        # a filesystem that refuses it must not break hosting.
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, INVITES_PATH)  # atomic, so a crash can't truncate it
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def remember_hosted(code: str, version_id: str, secret: str,
                    address: str | None = None) -> None:
    """Records a code this machine minted, with the secret that owns it."""
    canonical = normalize(code)
    if not canonical:
        raise ValueError(f"not a valid invite code: {code!r}")
    data = _load()
    data["hosted"][canonical] = {
        "version_id": version_id,
        "secret": secret,
        "address": address,
        "created": int(time.time()),
    }
    _save(data)


def remember_joined(code: str, address: str) -> None:
    """Records a code this machine joined, for a recent-servers list."""
    canonical = normalize(code)
    if not canonical:
        raise ValueError(f"not a valid invite code: {code!r}")
    data = _load()
    data["joined"][canonical] = {"address": address, "last_joined": int(time.time())}
    _save(data)


def get_hosted(version_id: str) -> tuple[str, dict] | None:
    """The most recent code minted for this version, or None.

    Reused rather than minting a new one on every host click - a code the host
    already sent to friends has to keep working across restarts, which is the
    entire reason the indirection exists.
    """
    data = _load()
    matches = [
        (code, meta) for code, meta in data["hosted"].items()
        if isinstance(meta, dict) and meta.get("version_id") == version_id
    ]
    if not matches:
        return None
    return max(matches, key=lambda pair: pair[1].get("created", 0))


def update_hosted_address(code: str, address: str) -> None:
    """Points an existing code at a new address.

    A tunnel endpoint can be renamed or reassigned by its provider, so the
    address behind a code is expected to change over its life. The code is not.
    """
    canonical = normalize(code)
    if not canonical:
        raise ValueError(f"not a valid invite code: {code!r}")
    data = _load()
    entry = data["hosted"].get(canonical)
    if entry is None:
        raise KeyError(f"no hosted record for {canonical}")
    entry["address"] = address
    _save(data)


def forget_hosted(code: str) -> bool:
    """Drops a hosted record. True if there was one."""
    canonical = normalize(code)
    if not canonical:
        return False
    data = _load()
    if canonical in data["hosted"]:
        del data["hosted"][canonical]
        _save(data)
        return True
    return False


def list_hosted() -> list[dict]:
    """Every code this machine has minted, newest first, without secrets.

    The secret is stripped because this feeds the UI and any debug logging
    around it - and `publish()` gets the secret from `get_hosted()` instead, so
    nothing legitimate needs it here. One stray `print(list_hosted())` in a
    support thread would otherwise hand over every code the host owns.
    """
    data = _load()
    out = [
        {"code": code, **{k: v for k, v in meta.items() if k != "secret"}}
        for code, meta in data["hosted"].items()
        if isinstance(meta, dict)
    ]
    return sorted(out, key=lambda e: e.get("created", 0), reverse=True)


def list_joined() -> list[dict]:
    """Every code this machine has joined, most recent first."""
    data = _load()
    out = [
        {"code": code, **meta}
        for code, meta in data["joined"].items()
        if isinstance(meta, dict)
    ]
    return sorted(out, key=lambda e: e.get("last_joined", 0), reverse=True)


# --------------------------------------------------------------------------
# Network client for worker/cubeon-invites.js.
#
# Every function here returns a result dict and raises nothing the caller has
# to handle. That is not laziness - these run from UI click handlers on
# background threads, where an escaped exception means a silent dead button.
# The caller checks `ok` and shows `message`, which is already a finished
# human sentence.
# --------------------------------------------------------------------------

# NOT DEPLOYED YET. The name mirrors the skins Worker
# (cubeon-skins.hamza-457-shahbaz.workers.dev) because it's the same account;
# deploy steps are in worker/README.md. Overridable so it can be pointed at
# `wrangler dev` without editing shipped code.
DEFAULT_API_ROOT = "https://cubeon-invites.hamza-457-shahbaz.workers.dev"

# Short: this sits between "click Host" and a code the user can send. A hung
# request here reads as a broken launcher, and failing fast lets the UI say so.
TIMEOUT = (5, 10)  # (connect, read)

# How many fresh codes to try before giving up on a collision. Against 152
# billion codes a single retry is already absurd; the loop exists so that if the
# code space is ever narrowed, the failure is a retry rather than a dead button.
MAX_MINT_ATTEMPTS = 4

# The Worker's machine-readable `error` values, turned into sentences a kid
# reads once and understands. Anything unmapped falls back to a generic line -
# never a raw error code, and never a stack trace.
_MESSAGES = {
    "missing_secret": "Cubeon couldn't prove this code is yours. Make a new invite.",
    "not_yours": "This invite belongs to another computer, so it can't be changed here.",
    "code_taken": "That code is already in use. Cubeon will pick a different one.",
    "blocked": "This invite was blocked for breaking the rules.",
    "bad_address": "The tunnel address looked wrong, so the invite wasn't published.",
    "bad_field": "The version or loader name looked wrong, so the invite wasn't published.",
    "bad_body": "Cubeon and the invite server disagreed about the request format.",
}

_OFFLINE = ("Couldn't reach the Cubeon invite server. Check your internet, "
            "or share the address directly.")


def _api_root(base_url: str | None = None) -> str:
    return (base_url
            or os.environ.get("CUBEON_INVITE_API")
            or DEFAULT_API_ROOT).rstrip("/")


def _fail(error: str, message: str | None = None, **extra) -> dict:
    return {"ok": False, "error": error,
            "message": message or _MESSAGES.get(error, _OFFLINE), **extra}


def _from_response(resp) -> dict:
    """Turns a non-2xx Worker response into a result dict."""
    try:
        error = (resp.json() or {}).get("error") or f"http_{resp.status_code}"
    except ValueError:
        error = f"http_{resp.status_code}"
    return _fail(error, status=resp.status_code)


def publish(code: str, secret: str, address: str, *,
            version: str | None = None, loader: str | None = None,
            base_url: str | None = None) -> dict:
    """Points a code at an address, claiming it if it's free.

    Safe to call on every server start with the same code - the Worker skips
    the write when nothing changed, which matters because KV's free tier allows
    far fewer writes per day than reads.

    On success also updates the local record, so the host's own UI and the
    server agree without a second round-trip.
    """
    canonical = normalize(code)
    if not canonical:
        return _fail("bad_code", f"{code!r} isn't a valid invite code.")

    payload = {"address": address}
    if version:
        payload["version"] = version
    if loader:
        payload["loader"] = loader

    try:
        resp = requests.put(
            f"{_api_root(base_url)}/i/{canonical}",
            json=payload,
            headers={"Authorization": f"Bearer {secret}"},
            timeout=TIMEOUT,
        )
    except requests.RequestException as ex:
        log.warning("invite publish failed: %s", ex.__class__.__name__)
        return _fail("offline", _OFFLINE)

    if resp.status_code != 200:
        return _from_response(resp)

    try:
        body = resp.json()
    except ValueError:
        return _fail("bad_response", _OFFLINE)

    try:
        update_hosted_address(canonical, address)
    except KeyError:
        # Published a code this machine has no record of - unusual but harmless
        # (a hand-typed code, or invites.json was cleared). The publish stands.
        pass

    return {"ok": True, "code": canonical, "address": address,
            "written": bool(body.get("written")),
            "claimed": bool(body.get("claimed"))}


def publish_new(version_id: str, address: str, *,
                version: str | None = None, loader: str | None = None,
                base_url: str | None = None) -> dict:
    """Mints a fresh code, claims it, and remembers it locally.

    Retries on the (vanishingly unlikely) collision, because the alternative is
    surfacing "that code is taken" to someone who never chose it.

    Deliberately does NOT reuse an existing code for this version - reuse is
    `get_hosted()` + `publish()`, and the difference is a decision the caller
    has to make on purpose: minting a new code invalidates nothing, but it does
    mean the link the host already sent their friends now points at nothing.
    """
    last = None
    for _ in range(MAX_MINT_ATTEMPTS):
        code = generate()
        secret = generate_secret()
        # Written down *before* the network call. If the process dies mid-flight
        # the secret is on disk, so the code stays repointable; the reverse
        # order would strand a claimed code with no way to ever update it.
        remember_hosted(code, version_id, secret, address=None)

        result = publish(code, secret, address, version=version,
                         loader=loader, base_url=base_url)
        if result["ok"]:
            return result

        forget_hosted(code)  # never claimed it, so don't keep a dead record
        last = result
        if result.get("error") != "code_taken":
            return result  # offline, blocked, bad address - retrying won't help

    return last or _fail("offline", _OFFLINE)


def resolve(code: str, *, base_url: str | None = None) -> dict:
    """Looks up the address behind a code.

    Returns `ok: False` with `error: "unknown"` for a code that doesn't
    resolve - which covers a typo, a host who stopped, and a code old enough to
    have expired. Those are indistinguishable from here by design (the Worker
    doesn't keep tombstones), so the message names all three rather than
    guessing one.
    """
    canonical = normalize(code)
    if not canonical:
        return _fail("bad_code", "That doesn't look like a Cubeon invite code. "
                                 "It should look like CUBE-7F4K-9QMN.")

    try:
        resp = requests.get(f"{_api_root(base_url)}/i/{canonical}", timeout=TIMEOUT)
    except requests.RequestException as ex:
        log.warning("invite resolve failed: %s", ex.__class__.__name__)
        return _fail("offline", _OFFLINE)

    if resp.status_code == 404:
        return _fail("unknown",
                     "No server found for that code. Check for a typo, or ask "
                     "your friend to press Host again. Codes expire after a day.")
    if resp.status_code != 200:
        return _from_response(resp)

    try:
        body = resp.json()
    except ValueError:
        return _fail("bad_response", _OFFLINE)

    address = body.get("address")
    if not isinstance(address, str) or ":" not in address:
        return _fail("bad_response", _OFFLINE)

    remember_joined(canonical, address)
    return {"ok": True, "code": canonical, "address": address,
            "version": body.get("version"), "loader": body.get("loader"),
            "age": body.get("age"), "expires_in": body.get("expires_in")}


def unpublish(code: str, secret: str, *, base_url: str | None = None) -> dict:
    """Takes a code offline, so joining it fails fast instead of timing out.

    Called when the host stops their server. Treats "already gone" as success:
    the caller wanted the code not to resolve, and it doesn't.
    """
    canonical = normalize(code)
    if not canonical:
        return _fail("bad_code", f"{code!r} isn't a valid invite code.")

    try:
        resp = requests.delete(
            f"{_api_root(base_url)}/i/{canonical}",
            headers={"Authorization": f"Bearer {secret}"},
            timeout=TIMEOUT,
        )
    except requests.RequestException as ex:
        log.warning("invite unpublish failed: %s", ex.__class__.__name__)
        return _fail("offline", _OFFLINE)

    if resp.status_code in (204, 404):
        return {"ok": True, "code": canonical}
    return _from_response(resp)
