"""
End-to-end encryption for Cubeon direct messages.

WHY THIS EXISTS

The friends relay (worker/cubeon-friends.js) is a free Cloudflare Worker, and
free Workers have no business holding plaintext chat. This module makes the
relay a dumb pipe for DMs: it only ever sees a JSON *envelope* whose body
("ct") is ciphertext. Only the two friends - whose keys never leave their own
launchers - can read a message.

This is a static-ECDH scheme per conversation:

  * Each machine owns one X25519 private key, stored next to its Cubeon
    identity (identity.json, field "e2ee_sk", 0600). Rotating it is simply a
    matter of deleting that field; old messages stay readable because every
    envelope carries the sender's public key ("spub") that was used to seal it.
  * To send, the launcher fetches the friend's public key (GET /pubkey/<name>),
    does X25519 with its own private key, and runs HKDF-SHA256 over the shared
    secret with an info string bound to the two friends' names. So even the
    *key schedule* is scoped to the conversation, not just the cipher.
  * To receive, the recipient derives the same key from its own private key and
    the "spub" embedded in the envelope. No key lookup is needed to read mail.

The name binding has one consequence the rest of the stack relies on: both
sides must agree on the two names at the bottom of the info string, which is
why it is sorted lowercase - "BlueFox <-> ruby" and "ruby <-> BlueFox" derive
the same key regardless of who sends first or how the names are cased.

THE ENVELOPE - every field is frozen; the relay stores it verbatim

    {"v": 1,                  # envelope version; anything else is refused
     "from": <display name>,  # the sender, as this machine knows itself
     "to": <display name>,    # the recipient
     "ts": <unix ms>,
     "spub": <urlsafe b64 of the sender's X25519 public key>,
     "nonce": <urlsafe b64 of the 12-byte AES-GCM nonce>,
     "ct": <urlsafe b64 of the ciphertext||tag>}

    key = HKDF(SHA256, 32, salt=None,
               info="cubeon-friends-e2ee-v1|" +
                    sorted([from.lower(), to.lower()]).join("|"))
              .derive(X25519(my_priv, peer_pub))

The scheme is deterministic to implement on both Python (this module) and any
future port, and it needs no network round-trip to decrypt. Failures are
deliberately specific: a version this code doesn't speak raises ValueError; a
wrong key or a tampered ciphertext raises cryptography's InvalidTag - the two
cases a caller must tell apart.

The `cryptography` dependency is optional exactly like cubeon/voice.py's audio
add-on: if it's missing, chat simply can't encrypt/decrypt (every entry point
raises a clear RuntimeError) instead of breaking the launcher at import time.
"""
import base64
import json
import logging
import os
import secrets
import time

log = logging.getLogger(__name__)

try:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric.x25519 import (
        X25519PrivateKey,
        X25519PublicKey,
    )
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )
    _HAVE_CRYPTO = True
except Exception:  # pragma: no cover - depends on the optional add-on
    InvalidTag = None
    hashes = X25519PrivateKey = X25519PublicKey = AESGCM = HKDF = None
    Encoding = NoEncryption = PrivateFormat = PublicFormat = None
    _HAVE_CRYPTO = False

# Frozen wire values. Changing any of these breaks every key already derived.
_VERSION = 1
_INFO_PREFIX = b"cubeon-friends-e2ee-v1|"
_NONCE_BYTES = 12
_KEY_BYTES = 32

# identity.json field holding this machine's X25519 private key (urlsafe b64).
_KEY_FIELD = "e2ee_sk"

_MISSING_MSG = ("The 'cryptography' package isn't installed, so encrypted chat "
                "is unavailable. Install it with your launcher's Python to "
                "enable end-to-end encrypted direct messages.")


def is_available() -> bool:
    """True only when the cryptography add-on is importable. Chat should tell
    the player this is off rather than pretend, exactly like voice.py."""
    return _HAVE_CRYPTO


def _require() -> None:
    if not _HAVE_CRYPTO:
        raise RuntimeError(_MISSING_MSG)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _unb64(text) -> bytes:
    return base64.urlsafe_b64decode(str(text).encode("ascii"))


# ---------------------------------------------------------------------------
# The identity file half. The key lives in identity.json so it is covered by
# the same 0600 policy (and the same "lose the file, re-claim" story) as the
# owning secret - both are "leak me and someone can act as you".
# ---------------------------------------------------------------------------

def _read_identity(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def load_or_create_key(identity_path: str) -> bytes:
    """This machine's 32-byte X25519 private key, creating it if needed.

    Reads `identity_path` (identity.json), keeps whatever fields it already
    holds, adds/updates only the "e2ee_sk" field (urlsafe b64 of the raw key),
    and rewrites the file atomically with 0600. Returns the raw key bytes.

    A fresh key is generated from the OS RNG and never leaves this machine;
    only its public half is ever published.
    """
    _require()
    identity = _read_identity(identity_path)
    existing = identity.get(_KEY_FIELD)
    if isinstance(existing, str):
        try:
            raw = _unb64(existing)
            if len(raw) == _KEY_BYTES:
                return raw
        except (ValueError, TypeError):
            pass  # corrupt field - fall through and mint a fresh key

    priv = X25519PrivateKey.generate()
    raw = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    identity[_KEY_FIELD] = _b64(raw)
    _write_identity(identity_path, identity)
    return raw


def _write_identity(path: str, identity: dict) -> None:
    """Atomic 0600 rewrite of identity.json, preserving every existing field."""
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    except OSError:
        pass
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(identity, f, indent=2)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
    except OSError:
        log.debug("couldn't persist the e2ee key", exc_info=True)
        try:
            os.unlink(tmp)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Key math.
# ---------------------------------------------------------------------------

def _priv(raw: bytes) -> "X25519PrivateKey":
    return X25519PrivateKey.from_private_bytes(raw)


def public_key_b64(priv: bytes) -> str:
    """The urlsafe-b64 public half of `priv` - what friends fetch to write to
    you, and what goes in an envelope's "spub"."""
    _require()
    pub = _priv(priv).public_key()
    raw_pub = pub.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return _b64(raw_pub)


def derive_shared(priv: bytes, peer_pub_b64: str) -> bytes:
    """The raw X25519 shared secret with `peer_pub_b64`. Not a key yet - the
    name-bound HKDF in _derive_key turns it into one."""
    _require()
    peer = X25519PublicKey.from_public_bytes(_unb64(peer_pub_b64))
    return _priv(priv).exchange(peer)


def _derive_key(shared: bytes, my_name: str, peer_name: str) -> bytes:
    """HKDF over the shared secret, bound to the two friends' (sorted, lower-
    cased) names so a key can't be replayed across conversations."""
    names = sorted([str(my_name or "").lower(), str(peer_name or "").lower()])
    info = _INFO_PREFIX + "|".join(names).encode("utf-8")
    return HKDF(algorithm=hashes.SHA256(), length=_KEY_BYTES,
                salt=None, info=info).derive(shared)


# ---------------------------------------------------------------------------
# Envelope seal / open.
# ---------------------------------------------------------------------------

def encrypt_dm(priv: bytes, peer_pub_b64: str, my_name: str, peer_name: str,
               text: str) -> dict:
    """Seals `text` for the friend who owns `peer_pub_b64`. Returns the dict
    that goes, JSON-encoded, as the DM's body - the relay stores and forwards
    it without ever being able to read it."""
    _require()
    shared = derive_shared(priv, peer_pub_b64)
    key = _derive_key(shared, my_name, peer_name)
    nonce = secrets.token_bytes(_NONCE_BYTES)
    ct = AESGCM(key).encrypt(nonce, str(text or "").encode("utf-8"), None)
    return {
        "v": _VERSION,
        "from": my_name,
        "to": peer_name,
        "ts": int(time.time() * 1000),
        "spub": public_key_b64(priv),
        "nonce": _b64(nonce),
        "ct": _b64(ct),
    }


def decrypt_dm(priv: bytes, my_name: str, envelope: dict) -> str:
    """Opens an envelope addressed to this machine. `my_name` is OUR name (the
    KDF info is symmetric, so either side's view of the conversation works).

    Raises ValueError for an envelope version this code doesn't speak, and
    cryptography's InvalidTag when the key doesn't match or the ciphertext was
    tampered with - the two cases a caller has to handle differently.
    """
    _require()
    if not isinstance(envelope, dict):
        raise ValueError("not an e2ee envelope")
    if envelope.get("v") != _VERSION:
        raise ValueError(f"unsupported e2ee envelope version {envelope.get('v')!r}")
    peer_name = envelope.get("from")
    spub = envelope.get("spub")
    if not isinstance(peer_name, str) or not isinstance(spub, str):
        raise ValueError("envelope is missing the sender name or public key")
    shared = derive_shared(priv, spub)
    key = _derive_key(shared, my_name, peer_name)
    try:
        nonce = _unb64(envelope.get("nonce"))
        ct = _unb64(envelope.get("ct"))
        if len(nonce) != _NONCE_BYTES:
            raise InvalidTag()
    except (ValueError, TypeError):
        raise InvalidTag()  # malformed fields are indistinguishable from tampering
    plain = AESGCM(key).decrypt(nonce, ct, None)
    return plain.decode("utf-8")
