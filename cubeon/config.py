"""
Launcher config persistence, offline ("cracked") auth, and the version-safe
FilePicker helper shared by every tab that lets the user pick a file.
"""
import inspect
import json
import os
import re
import secrets
import uuid

from .paths import CONFIG_PATH, CUBEON_HOME


def get_system_ram_mb() -> int:
    """Total physical RAM on this machine, in MB. Falls back to 8192 if it
    can't be detected (psutil missing, or a platform read failure) so the
    RAM slider always has *some* sane ceiling instead of crashing."""
    try:
        import psutil
        return int(psutil.virtual_memory().total / (1024 * 1024))
    except Exception:
        pass

    # psutil isn't installed / failed - try a platform-native fallback
    # before giving up.
    try:
        import platform
        if platform.system() == "Linux":
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return kb // 1024
        elif platform.system() == "Darwin":
            import subprocess
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"])
            return int(out.strip()) // (1024 * 1024)
        elif platform.system() == "Windows":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return int(stat.ullTotalPhys / (1024 * 1024))
    except Exception:
        pass

    return 8192  # last-resort fallback so callers never see 0/None


def recommended_max_ram_mb(system_ram_mb: int) -> int:
    """Half of detected system RAM, rounded down to the nearest 512 MB
    step, with a 1024 MB floor. This is the launcher's *default* and the
    point past which we warn - not a hard cap; players can still go
    higher if they choose to."""
    half = system_ram_mb // 2
    half = (half // 512) * 512
    return max(half, 1024)

DEFAULT_CONFIG = {
    "username": "Player",
    "ram_mb": 4096,
    "last_version": None,
    "java_path": None,  # None = auto-detect
    "width": 1280,
    "height": 720,
    "active_skin": None,  # filename (in SKINS_DIR) of the uploaded skin to use, or None
    # filename (in CAPES_DIR) of the uploaded cape to use, or None = the shared
    # Cubeon cape (the Worker serves that to everyone; see worker/cubeon-skins.js).
    "active_cape": None,
    # Username the active skin was last mirrored to CustomSkinLoader under, so a
    # rename can clean up the stale <OLDNAME>.png instead of leaving it behind.
    "csl_synced_name": None,
    # Same bookkeeping for the active cape's LocalSkin/capes/<NAME>.png mirror.
    "csl_synced_cape_name": None,
    # Let Cubeon install CustomSkinLoader and register its own skin/cape
    # sources with it. Without that mod, offline players see Steve/Alex and no
    # Cubeon cape - so this is on by default and making the user install it by
    # hand is not an option. Turning it off is the supported opt-out; see
    # cubeon/csl.py for exactly what it stops doing.
    "manage_skin_mod": True,
    "server_ram_mb": 2048,  # RAM allocated to the local server started from the Server tab
    # Whether Smooth mode (low-ping optimization) is ON per server version.
    # Stored explicitly rather than inferred from server.properties, because
    # saving unrelated settings rewrites view/simulation-distance from the
    # dropdowns and would otherwise silently revert the switch's state.
    "high_ping_optimization": {},  # {version_id: bool}
    "profile_picture": None,  # filename (in PFP_DIR) of the uploaded profile picture, or None
    # The claimed Cubeon name (the unique social handle used by the Friends tab).
    # Distinct from "username", which is the impersonable in-game name - the
    # owning secret for this lives in identity.json (0600), see cubeon/friends.py.
    "cubeon_name": None,
    # Optional per-version display nicknames, keyed by launch id, e.g.
    # {"1.20.1": "Main survival"}. Renaming an instance sets one of these
    # instead of touching the on-disk folder/id - a folder rename would
    # break loader detection (which parses the id) and any modpack that
    # references the launchable id, whereas a label is purely cosmetic and
    # can never stop a version from launching. Cleared when a version is
    # deleted.
    "version_labels": {},
    # Discord Rich Presence - show a "Cubeon" activity on your Discord profile
    # (like TLauncher shows itself as a game). Requires the Discord desktop app
    # running on this machine AND discord_client_id set; see
    # cubeon/discord_rpc.py for the Discord-side steps.
    "discord_rpc_enabled": True,
    # Discord Application ID. Shipped with Cubeon's own app ID so Rich Presence
    # works out of the box on every install (Discord desktop app must be
    # running on the same machine).
    "discord_client_id": "1542920123763925122",
    # Optional art-asset image key (from Discord's Rich Presence -> Art Assets)
    # shown as the big icon next to the activity, and its hover text.
    "discord_large_image": "1a92fe8fac941f333d508efe568a88ffccfc8af1b7ccb66ff62bf93822a9b47a",
    "discord_large_text": "Cubeon",
}


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r") as f:
            data = json.load(f)
        return {**DEFAULT_CONFIG, **data}
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        # Brand-new install, no config on disk yet - seed ram_mb with half
        # of *this machine's* RAM instead of the static 4096 fallback in
        # DEFAULT_CONFIG, so a low-RAM machine doesn't start over-allocated
        # (and a high-RAM one isn't stuck under-using what it has).
        cfg = dict(DEFAULT_CONFIG)
        try:
            cfg["ram_mb"] = recommended_max_ram_mb(get_system_ram_mb())
        except Exception:
            pass
        return cfg


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def offline_uuid(username: str) -> str:
    """Vanilla offline UUID = md5("OfflinePlayer:" + name), version-3-ish bits set."""
    return str(uuid.uuid3(uuid.NAMESPACE_DNS, f"OfflinePlayer:{username}"))


# ---------------------------------------------------------------------------
# Stable machine identity - auth_key.json
#
# Dual-layer identity model. Skins are anchored strictly to a persistent UUID
# v4 while display names are ephemeral pointers (Username -> UUID) on the
# backend - so the file holds two halves with very different exposure:
#
#   public_uuid   the random v4 UUID passed to Minecraft via --uuid AND used
#                 as the master skin key on the Worker. NOT secret: it ends
#                 up on servers you play on.
#   secret_token  the private capability key ("sec_" + 64 hex) kept strictly
#                 on this machine. Every backend write for this UUID -
#                 heartbeat pointer updates, skin uploads - must present it
#                 as a Bearer token; the Worker only ever stores its SHA-256.
#
# Everything that must survive a rename binds to public_uuid:
#   * the in-game player UUID (so renaming never resets saves/inventory),
#   * skin/cape ownership on the network,
#   * the Friends/chat identity (the claimed Cubeon name is owned by THIS
#     secret, so the name is just a public handle over a stable account).
#
# 0600 - the secret is the one genuinely sensitive value here (leak it and
# someone can act as you; lose it and you mint a new identity).
#
# ensure_auth_key() is idempotent and self-healing: a missing file is created,
# and a corrupt/partial one is repaired in place (never silently discarded, so
# a readable secret is preserved even if the surrounding JSON got mangled).
# Installs written before the rename ({uuid, secret} keys) are migrated in
# place - both halves keep their values, only the JSON keys change, so an
# existing install neither loses its identity nor re-registers anywhere.
# ---------------------------------------------------------------------------

AUTH_KEY_PATH = os.path.join(CUBEON_HOME, "auth_key.json")

# A canonical v4 UUID string (8-4-4-4-12 hex). Used to validate what we read
# back before trusting it as the launch/identity UUID.
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _new_secret() -> str:
    """Private capability token: "sec_" + 128 bits of hex (64 hex chars).
    High-entropy and URL/header-safe, per the identity API's Bearer scheme."""
    return f"sec_{uuid.uuid4().hex}{uuid.uuid4().hex}"


def ensure_auth_key() -> dict:
    """Loads the stable identity, creating or repairing auth_key.json as needed.

    Returns {"public_uuid": <v4 uuid str>, "secret_token": <sec_... token>}.
    Guaranteed to always return a usable identity: on any read/parse failure
    it regenerates the missing half rather than raising, so callers never have
    to handle "no identity yet". Self-healing - valid halves already on disk
    are preserved; only the missing/invalid field is minted. Legacy files
    keyed {uuid, secret} are migrated to the new names without regenerating
    either value (the uuid MUST survive migration or every server the player
    has ever joined would treat them as a brand-new player).

    Written 0600 (best-effort; a no-op on filesystems that don't support it
    must not break identity creation).
    """
    data = {}
    try:
        with open(AUTH_KEY_PATH, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, json.JSONDecodeError, ValueError):
        data = {}

    uid = data.get("public_uuid")
    secret = data.get("secret_token")
    if uid is None:
        uid = data.get("uuid")          # pre-rename file: keep the value
    if secret is None:
        secret = data.get("secret")     # ditto

    # Keep what's valid, mint what isn't. uuid4() is the "bullet-proof" part:
    # 122 random bits, so it never collides with anyone else's identity and,
    # unlike offline_uuid(name), never changes when the username does.
    dirty = False
    if not (isinstance(uid, str) and _UUID_RE.match(uid)):
        uid = str(uuid.uuid4())
        dirty = True
    if not (isinstance(secret, str) and len(secret) >= 16):
        secret = _new_secret()
        dirty = True

    identity = {"public_uuid": uid, "secret_token": secret}
    if dirty or data != identity:
        _write_auth_key(identity)
    return identity


def _write_auth_key(identity: dict) -> None:
    """Atomically persist auth_key.json with 0600. Best-effort: a write
    failure leaves the previous file intact and is non-fatal (the in-memory
    identity is still returned to the caller for this session)."""
    try:
        os.makedirs(CUBEON_HOME, exist_ok=True)
        tmp = AUTH_KEY_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(identity, f, indent=2)
        try:
            os.chmod(tmp, 0o600)  # tighten before the rename, never world-readable
        except OSError:
            pass
        os.replace(tmp, AUTH_KEY_PATH)  # atomic; a crash can't truncate it
    except OSError:
        try:
            os.unlink(AUTH_KEY_PATH + ".tmp")
        except OSError:
            pass


def stable_uuid() -> str:
    """The launch/identity UUID (public_uuid) from auth_key.json. This is what
    Minecraft is launched with (see launch.build_launch_command) and the master
    key every network skin binds to, so a rename never orphans the player's
    per-UUID server data or their published skin."""
    return ensure_auth_key()["public_uuid"]


def stable_secret() -> str:
    """The private capability token (secret_token) that authorizes every
    backend write for this machine's UUID - heartbeat pointers, skin uploads,
    Friends name claims. Never leaves this machine except as a Bearer header;
    the backend stores only its SHA-256."""
    return ensure_auth_key()["secret_token"]



def validate_username(username: str) -> tuple[bool, str]:
    if not username or not (3 <= len(username) <= 16):
        return False, "Username must be 3-16 characters"
    if not re.match(r"^[A-Za-z0-9_]+$", username):
        return False, "Only letters, numbers, and underscores allowed"
    return True, ""


def run_file_picker(page, file_picker, on_files=None, **kwargs):
    """
    Opens a Flet FilePicker's dialog and delivers the selected files to
    on_files(files), working across Flet versions:

      - Old Flet: pick_files(**kwargs) runs synchronously, opens the
        dialog immediately, and later fires file_picker.on_result with
        the selection - on_files is called from inside that handler.
      - New Flet (0.80+): pick_files() is async and returns the picked
        files directly (`files = await file_picker.pick_files(...)`)
        instead of guaranteeing on_result fires. Calling it as a plain
        sync call from a non-async on_click just creates a coroutine
        that's never awaited - no dialog opens, and Python prints
        "coroutine was never awaited". Worse, even if awaited, relying
        on_result to also fire is not guaranteed on this API, which is
        why uploads could silently go nowhere even once the dialog did
        open. So on this path we await the coroutine ourselves and call
        on_files with whatever it returns, instead of depending on
        on_result at all.

    on_files receives a list of picked file objects (or an empty list /
    None if the dialog was cancelled) - same shape either way, so the
    caller's logic doesn't need to know which Flet version is running.

    Takes `page` and `file_picker` as plain objects (not type-hinted as
    Flet classes) so this module doesn't need to import flet itself.
    """
    result = file_picker.pick_files(**kwargs)
    if inspect.isawaitable(result):
        # New-Flet path. Temporarily detach on_result for the duration of
        # this pick - if the async pick_files() call also ends up firing
        # on_result under some Flet builds, we don't want on_files to run
        # twice (double "Uploading..." / double file copy) for one pick.
        _prev_on_result = getattr(file_picker, "on_result", None)
        file_picker.on_result = None

        async def _await_it():
            try:
                files = await result
                if on_files is not None:
                    on_files(files)
            finally:
                file_picker.on_result = _prev_on_result

        run_task = getattr(page, "run_task", None)
        if callable(run_task):
            run_task(_await_it)
        else:
            # No page.run_task on this Flet version - nothing more we can
            # do without it, since the coroutine can't run on its own.
            file_picker.on_result = _prev_on_result
    # Old Flet: pick_files() already ran synchronously and will deliver
    # the result via file_picker.on_result, as originally wired by the
    # caller - nothing further to do here.
