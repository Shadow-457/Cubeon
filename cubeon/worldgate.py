"""
Worldgate - the optional password on a P2P LAN world session.

CubeonGate (gate.py) passwords the *dedicated* Paper server. A LAN world that
goes through the P2P session (invite -> punch -> handover, Minekube on
fallback) had no gate at all: whoever accepted the invite got the connection
target - the relay port or the <endpoint>.play.minekube.net address - with no
questions asked. This module adds that gate, and friends_service enforces it
at the one point that matters: the host sends its p2p_offer (which carries the
LAN port and the relay session token) only AFTER the joiner proves they know
the password. No proof, no offer, no address.

LIFETIME: this is deliberately EPHEMERAL. The password is chosen when the host
opens their world to LAN (the mod's password prompt) and forgotten when the
session ends - nothing is written to disk, not even the hash, and the
plaintext is never stored anywhere on the joiner's side either (it lives in
the session dict only long enough to answer one challenge).

PROTOCOL (over the friends relay's E2EE-signalled P2P room):

  host -> joiner: gate_challenge {challenge, salt_hex, iterations}
  joiner -> host: gate_proof    {proof_hex}
                  proof = HMAC-SHA256(key=PBKDF2(password, salt), challenge)
  host -> joiner: gate_ok | gate_fail {left, challenge}

The joiner derives the same PBKDF2 key from the salt the challenge carries,
so the host can verify against its stored hash with a constant-time compare.
The challenge is a fresh 128-bit nonce per round, so a proof cannot be
replayed for a later session, and the relay never sees anything but opaque
hex (it is E2EE-signed on top of that).
"""
import hashlib
import hmac
import secrets
import threading

# Same parameters as gate.py / CubeonGate - shared constants, deliberately.
from .gate import PBKDF2_ITERATIONS, PBKDF2_KEY_BITS, MIN_PASSWORD_LEN

log = __import__("logging").getLogger(__name__)

# How many wrong proofs a joiner gets before the host closes the room.
# CubeonGate's own escalation starts at 3; staying consistent beats inventing
# a second number for the same idea.
MAX_ATTEMPTS = 3

_lock = threading.Lock()
_record = None   # {"salt_hex", "hash_hex", "iterations"} | None


class WorldGateError(Exception):
    """A world-password problem with a message meant for the user."""


def set_password(password: str) -> None:
    """Arms the gate for the world being hosted right now.

    Only a random salt + PBKDF2 hash is kept - the same shape CubeonGate
    stores, but in memory only. Raises WorldGateError on a too-short
    password; the caller shows the message as-is."""
    global _record
    password = (password or "").strip()
    if len(password) < MIN_PASSWORD_LEN:
        raise WorldGateError(
            f"The world password must be at least {MIN_PASSWORD_LEN} characters.")
    salt = secrets.token_bytes(16)
    key = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt,
        PBKDF2_ITERATIONS, dklen=PBKDF2_KEY_BITS // 8)
    with _lock:
        _record = {
            "salt_hex": salt.hex(),
            "hash_hex": key.hex(),
            "iterations": PBKDF2_ITERATIONS,
        }
    log.info("worldgate: password set (in memory only)")


def clear() -> None:
    """Disarms the gate (Skip, or the session ended)."""
    global _record
    with _lock:
        _record = None


def has_password() -> bool:
    with _lock:
        return _record is not None


def record() -> "dict | None":
    """A copy of the stored record (salt/hash/iterations), or None. The hash
    is what the host broadcasts inside the challenge - it is a key-derivation
    INPUT, not a capability: knowing it doesn't let anyone answer a fresh
    challenge without the password."""
    with _lock:
        return dict(_record) if _record else None


def new_challenge() -> str:
    """A fresh 128-bit nonce for one proof round."""
    return secrets.token_hex(16)


def compute_proof(challenge: str, password: str,
                  salt_hex: str, iterations: int) -> str:
    """The joiner's answer: HMAC(key=PBKDF2(password, salt), challenge), hex.

    Separated from send-side plumbing so tests can pin the exact bytes."""
    key = hashlib.pbkdf2_hmac(
        "sha256", (password or "").strip().encode("utf-8"),
        bytes.fromhex(salt_hex), int(iterations or PBKDF2_ITERATIONS),
        dklen=PBKDF2_KEY_BITS // 8)
    return hmac.new(key, (challenge or "").encode("utf-8"),
                    hashlib.sha256).hexdigest()


def verify(challenge: str, proof_hex: str) -> bool:
    """Host side: does this proof match the armed password? Never raises for
    a wrong answer - returns False (an unusable proof is a wrong answer)."""
    with _lock:
        record = _record
    if not record:
        return False
    try:
        key = bytes.fromhex(record["hash_hex"])
    except (KeyError, ValueError):
        return False
    expected = hmac.new(key, (challenge or "").encode("utf-8"),
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, str(proof_hex or "").lower())
