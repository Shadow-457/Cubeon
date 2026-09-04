"""
CubeonGate - the server password gate.

The owner sets a join password; the CubeonGate Paper plugin (shipped as a
compiled jar in assets/, sources in gate_plugin/) enforces it per UUID on
the server BEFORE the player spawns: no movement, no commands, no chat, no
interaction - only the password screen. The exact wording the player sees:

    Cubeon security check: This password is required for your server to
    be safe and playable.

This module is the launcher half of that: install the plugin, and manage
the credentials file the plugin reads.

SECURITY MODEL (mirrors the plugin's - see CubeonGate.java):

  * Only a random salt + a PBKDF2-HmacSHA256 hash (60k iterations, the
    exact same parameters the plugin verifies with) is ever stored - never
    the password. credentials.json is written 0600.
  * A correct answer verifies the player's UUID in the plugin's
    state.json, so the prompt never annoys them again - until the owner
    changes the password, which wipes every verified UUID (both sides
    agree on this: set_password deletes state.json, and the plugin
    independently detects a credentials fingerprint change and clears its
    in-memory verified set).
  * Failures escalate persistently: 3rd wrong attempt locks that UUID out
    for 10 minutes, 4th for 20, doubling each further failure. The plugin
    persists counters and lockouts across restarts, so "just reconnect"
    or "restart the server" resets nothing.
  * The plugin re-reads credentials on every check rather than caching, so
    a password change can never leave a stale hash authenticating.
"""
import base64
import hashlib
import json
import os
import secrets

from .paths import APP_NAME
from .server import (
    CONNECT_PLUGIN_NAME,
    get_plugins_dir,
)

log = __import__("logging").getLogger(__name__)

GATE_JAR_NAME = "CubeonGate.jar"
GATE_DATA_DIR = "CubeonGate"

# Same parameters as the plugin's verifier - they must never drift apart,
# or a password the launcher hashes would not be the password the server
# accepts. The plugin's constants are the source of truth; this comment
# exists so a change to one is visibly a change to both.
PBKDF2_ITERATIONS = 60_000
PBKDF2_KEY_BITS = 256

MIN_PASSWORD_LEN = 4


class GateError(Exception):
    """A password-gate problem with a message meant for the user."""


def _assets_dir() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")


def gate_jar_path(version_id: str) -> str:
    return os.path.join(get_plugins_dir(version_id), GATE_JAR_NAME)


def is_installed(version_id: str) -> bool:
    path = gate_jar_path(version_id)
    if not os.path.isfile(path) or os.path.getsize(path) < 1_000:
        return False
    try:
        with open(path, "rb") as f:
            return f.read(2) == b"PK"
    except OSError:
        return False


def install(version_id: str, *, force: bool = False) -> str:
    """Installs the shipped CubeonGate.jar into the server's plugins dir.

    Re-copies whenever the bundled jar differs from the installed one, so
    a Cubeon update ships a fixed plugin without the user having to know
    or care - a plugin this security-critical must never keep running an
    old version just because a file happens to exist."""
    src = os.path.join(_assets_dir(), GATE_JAR_NAME)
    if not os.path.isfile(src):
        raise GateError("CubeonGate.jar is missing from the Cubeon install.")
    dest = gate_jar_path(version_id)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(src, "rb") as f:
        head = f.read(2)
    if head != b"PK":
        raise GateError("The bundled CubeonGate.jar is corrupt.")
    if not force and os.path.isfile(dest):
        try:
            with open(dest, "rb") as f:
                if f.read() == open(src, "rb").read():
                    return dest  # already up to date
        except OSError:
            pass
    import shutil
    shutil.copyfile(src, dest)
    return dest


def _gate_data_dir(version_id: str) -> str:
    path = os.path.join(get_plugins_dir(version_id), GATE_DATA_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def credentials_path(version_id: str) -> str:
    return os.path.join(_gate_data_dir(version_id), "credentials.json")


def state_path(version_id: str) -> str:
    return os.path.join(_gate_data_dir(version_id), "state.json")


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt,
        PBKDF2_ITERATIONS, dklen=PBKDF2_KEY_BITS // 8).hex()


def set_password(version_id: str, password: str) -> None:
    """Sets (or changes) the join password.

    Only the salt + PBKDF2 hash are stored, 0600 - the plaintext exists
    only for the duration of this call. Changing the password deletes the
    plugin's state.json, so every previously verified UUID must answer the
    security check again - that's the point: a password someone already
    knows shouldn't keep working once it's replaced.
    """
    password = (password or "").strip()
    if len(password) < MIN_PASSWORD_LEN:
        raise GateError(
            f"The password must be at least {MIN_PASSWORD_LEN} characters.")
    salt = secrets.token_bytes(16)
    record = {
        "salt_hex": salt.hex(),
        "hash_hex": _hash_password(password, salt),
        "iterations": PBKDF2_ITERATIONS,
        # Version tag so a future algorithm change is detectable on read.
        "algo": "pbkdf2-hmac-sha256",
    }
    path = credentials_path(version_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile_mkstemp(os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(record, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError as ex:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise GateError(f"Couldn't save the password: {ex}") from ex
    # Force re-verification of everyone, including previously verified UUIDs.
    try:
        os.unlink(state_path(version_id))
    except OSError:
        pass
    log.info("gate: password set for %s (verified set cleared)", version_id)


def clear_password(version_id: str) -> None:
    """Turns the gate off: credentials removed, verified state removed."""
    for path in (credentials_path(version_id), state_path(version_id)):
        try:
            os.unlink(path)
        except OSError:
            pass


def has_password(version_id: str) -> bool:
    try:
        with open(credentials_path(version_id), "r", encoding="utf-8") as f:
            record = json.load(f)
        return bool(record.get("hash_hex")) and bool(record.get("salt_hex"))
    except (OSError, json.JSONDecodeError):
        return False


def verify_password(version_id: str, password: str) -> bool:
    """Local check that a password matches what the server will enforce.

    Used by the Friends-tab share flow so the owner can confirm what
    they're about to send a friend is the real password - typed blind,
    checked against the same PBKDF2 hash the server's plugin uses. Never
    raises for a wrong password; returns False."""
    try:
        with open(credentials_path(version_id), "r", encoding="utf-8") as f:
            record = json.load(f)
        salt = bytes.fromhex(record["salt_hex"])
        expected = bytes.fromhex(record["hash_hex"])
    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        return False
    iterations = record.get("iterations", PBKDF2_ITERATIONS)
    candidate = hashlib.pbkdf2_hmac(
        "sha256", (password or "").strip().encode("utf-8"), salt,
        iterations, dklen=PBKDF2_KEY_BITS // 8)
    # hmac.compare_digest: constant-time, same guarantee as the plugin's
    # MessageDigest.isEqual.
    import hmac
    return hmac.compare_digest(candidate, expected)


def set_display_address(version_id: str, address: str) -> None:
    """Publishes the server's public endpoint for the Tab-list branding.

    The plugin can't reliably know the address itself: a blank endpoint
    means Minekube assigns a random name that only exists after the
    Connect plugin announces it in the log. The launcher's watcher reads
    that announcement, so it drops the resolved address here; the plugin
    reads this file on every join (falling back to the Connect config's
    endpoint, then a plain tagline)."""
    path = os.path.join(_gate_data_dir(version_id), "address.txt")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write((address or "").strip())
    except OSError:
        pass


def tempfile_mkstemp(directory: str):
    import tempfile
    return tempfile.mkstemp(dir=directory, prefix=".gate-", suffix=".tmp")
