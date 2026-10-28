"""
Launcher config persistence, offline ("cracked") auth, and the version-safe
FilePicker helper shared by every tab that lets the user pick a file.
"""
import inspect
import json
import logging
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import time
import uuid

from .paths import CONFIG_PATH, CUBEON_HOME

_SAVE_LOCK = threading.Lock()
# A config.json that exists but cannot be read (antivirus lock, bad sector,
# half-synced cloud file) must not turn into "all defaults" for this session -
# the next save would overwrite the user's real settings. Keep the last good
# dict around; only an actually missing file may seed defaults.
_LOAD_LOCK = threading.RLock()
_LAST_GOOD_CONFIG: "dict | None" = None


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


# The most a brand-new install is seeded with, regardless of how much RAM the
# machine has. See load_config.
DEFAULT_HEAP_CEILING_MB = 6144

DEFAULT_CONFIG = {
    "username": "Player",
    "ram_mb": 4096,
    "last_version": None,
    "java_path": None,  # None = auto-detect
    # Launcher language (cubeon/i18n.py). None means "detect from the OS on
    # first run, then remember what was detected" - main.py persists the
    # resolved value, so a later boot on a differently-locale'd machine cannot
    # silently change the player's language. An unknown code falls back to
    # English rather than failing to start.
    "ui_language": None,
    "notify_message": True,
    # Extra JVM flags appended after Cubeon's own tuned defaults on every
    # client launch, e.g. "-Dsome.prop=value -XX:MaxGCPauseMillis=100". One
    # string, split on whitespace (quotes respected). A custom collector wins
    # over G1; other repeated options use the last value supplied.
    "custom_jvm_flags": "",
    "width": 1280,
    "height": 720,
    "active_skin": None,  # filename (in SKINS_DIR) of the uploaded skin to use, or None
    # filename (in CAPES_DIR) of the uploaded cape to use, or None = the shared
    # Cubeon cape (the Worker serves that to everyone; see worker/cubeon-skins.js).
    "active_cape": None,
    # The Cape pane's "None": hide the shared Cubeon cape on THIS player's
    # screen. Other players still see the shared cape, because the Worker
    # assigns it server-side - the local CustomSkinLoader source only wins the
    # slot on this machine. Ignored while a custom cape is selected.
    "hide_cubeon_cape": False,
    # Original Cubeon shoulder/back cosmetics (see cubeon/cosmetics.py).
    # The launcher writes the active ids to <game>/config/cubeon-cosmetics.json
    # and the client mod draws them as textured boxes on the player.
    "active_shoulder_item": None,
    "active_back_item": None,
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
    # Inject the Cubeon Client in-game mod (Friends button/screen) into
    # Fabric/Quilt profiles at launch. Turning this off launches a clean
    # install with no Cubeon mod at all - the launcher itself keeps working.
    # Distinct from features.friends_enabled(), which is a BUILD-time switch
    # that removes the whole Friends backend; this is the user's per-launch
    # choice about the jar.
    "client_mod_enabled": True,
    # With the Cubeon Client on, also make sure the client performance mods
    # that actually raise frame rate (Sodium, Lithium, ImmediatelyFast,
    # EntityCulling, MoreCulling, BadOptimizations, Krypton, ThreadTweak,
    # Dynamic FPS - fetched from Modrinth like any other mod) are present in
    # the Fabric/Quilt profile. It does NOT touch Vsync/maxFps (2026-10-24):
    # those are the player's frame pacing, and a fresh install keeps
    # Minecraft's own defaults (Vsync ON). See cubeon/game_options.py.
    # The Cubeon Client itself is a social mod and draws nothing expensive;
    # this is what turns "activate Cubeon Client" into a real FPS win.
    # Turning it off leaves the mod set and the game's options exactly as the
    # user built them.
    "perf_mods_enabled": True,
    # FPS boost (the Play-menu toggle): with the perf mods on, also set
    # Minecraft's own speed-only graphics options (Fast graphics, minimal
    # particles, no entity shadows, trimmed entity distance, biome blend 0,
    # chunk writes off the render thread - see cubeon/game_options.py
    # MAX_FPS_OPTIONS). Since 2026-10-18 it also LOWERS the distance levers
    # the frame rate actually lives on - renderDistance 6, simulationDistance
    # 5, mipmapLevels 2, 2D clouds - because a side-by-side run showed the
    # gap against FastClient was exactly those (it ships the same preset plus
    # distance 6, Cubeon shipped 8). OFF actively RESTORES Minecraft's
    # defaults for every one of those keys at every launch
    # (restore_vanilla_look), render distance included, so an install that ran
    # boosted goes back to fancy/shadowed vanilla looks and vanilla view
    # distance. Renamed from max_fps_enabled (2026-10-15); the old key is
    # migrated in load_config.
    "fps_boost_enabled": True,
    # How much the launcher animates: "full" (hover lifts, press dips, list
    # cascades, shimmering loading rows, the breathing bloom behind the Play
    # button) or "reduced" (colour and opacity fades only - nothing changes
    # size or position, nothing moves on its own). Read at startup into
    # cubeon/motion.py, and Settings > Display's Motion switch writes it live:
    # the level is consulted when an event fires, not when a control is built,
    # so flipping it takes effect on the rows that are already on screen. The
    # default is "full".
    "motion_level": "full",
    # Translucent ("glass") launcher window: the native window AND the page
    # canvas are painted with an alpha channel so the desktop shows through
    # faintly behind the UI. Only the BACKGROUND goes translucent - panels and
    # text keep full opacity, so contrast is unchanged. Best-effort on every
    # platform: a compositor/protocol that refuses alpha just shows the opaque
    # colours. The window alpha is set once at startup, so changing this needs
    # a relaunch. See BG_GLASS/SURFACE_GLASS in cubeon/theme.py.
    "glass_mode_enabled": True,
    # Custom window frame (Windows + Linux): drop the OS title bar and let
    # Cubeon's own top bar BE the title bar - the brand mark drags the window,
    # our own min/max/close buttons replace the system ones, and the window's
    # edges stay resizable through hot-zones wired to Window.start_resizing.
    #
    # The default is None, NOT False, and that is deliberate (2026-10-28 fix):
    # None means "this user has never chosen", so cubeon/winchrome.py's
    # platform default decides (branded frame ON for Windows and Linux, native
    # frame on macOS). A stored False used to be indistinguishable from an
    # explicit "turn it off", which is why Windows 10 users who never touched
    # the Settings toggle never saw the branded frame: the merged config
    # handed the policy a hard False and its platform branch never ran.
    # The window frame is set once at startup, so changing it needs a relaunch
    # (same contract as glass_mode_enabled). CUBEON_CUSTOM_CHROME=0/1 overrides
    # either way. See cubeon/winchrome.py for the policy, settings_tab.py for
    # the toggle.
    "custom_window_chrome": None,
    # Whether the user has actually touched the Custom window frame toggle.
    # load_config flips a legacy un-chosen False to the platform default ONCE;
    # after the first real toggle this marker makes the choice stick.
    "custom_window_chrome_chosen": False,
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
    # Discord Rich Presence - show a "Cubeon" activity on your Discord profile
    # (like TLauncher shows itself as a game). Requires the Discord desktop app
    # running on this machine AND discord_client_id set; see
    # cubeon/discord_rpc.py for the Discord-side steps. Shipped with Cubeon's
    # own app ID so Rich Presence works out of the box on every install
    # (Discord desktop app must be running on the same machine).
    "discord_client_id": "1542920123763925122",
    # Optional art-asset image key (from Discord's Rich Presence -> Art Assets)
    # shown as the big icon next to the activity, and its hover text.
    "discord_large_image": "1a92fe8fac941f333d508efe568a88ffccfc8af1b7ccb66ff62bf93822a9b47a",
    "discord_large_text": "Cubeon",

    # --- Seasonal look (see cubeon/seasonal.py) ---------------------------
    # Wear the palette of the season the user is actually in, detected from the
    # timezone at startup (autumn/spring/winter/summer templates). The palette
    # is bound at import time, so changing this needs a relaunch - the Settings
    # pane says so, and offers to do it. Turning it off just keeps the normal
    # green identity. ON BY DEFAULT (2026-10-23 user ask): the seasonal look is
    # the launcher's identity now, and a first run should wear it rather than
    # looking like every other green launcher. Ambience stays opt-in below.
    "seasonal_theme": True,
    # "auto" = follow the detected season. A season name overrides the guess,
    # for the two cases detection can't win: a user who disagrees with it, and
    # the tropics/equator, where "autumn" is a fiction either way. The Settings
    # override ALWAYS outranks the timezone tables.
    "season_override": "auto",
    # The little companion in the top bar (assets/pets/<season>.gif). Pure
    # decoration - it costs no timer of its own, the GIF animates itself.
    # On with the seasonal look by default.
    "season_pet": True,
    # Falling leaves / snow / petals / fireflies in the corner. Opt-in AND
    # off by default: it is the only part of the seasonal layer that needs a
    # repaint clock, so it ships disabled until it has been measured on real
    # hardware (CUBEON_PERF=1).
    "season_ambience": False,
    # "2026-autumn" - the last season the greeting card was shown for, so the
    # once-a-season hello happens once, including across the Dec->Jan boundary
    # (see seasonal.season_year).
    "season_seen": None,

    # --- Disk hygiene (see cubeon/maintenance.py) -------------------------
    # Let Cubeon tidy its own folders at startup: merge stray Minecraft asset
    # objects back into assets/objects/, drop superseded duplicates from the
    # global mod/content stores, archive foreign-launcher leftovers to
    # <game>/_legacy/ and clear .part/.tmp debris. It never touches game
    # content (saves, versions, mods, packs, worlds). Turning this off leaves
    # the folders exactly as they are; the Settings > Game versions "Tidy up
    # files" action still works on demand.
    "auto_organize_files": True,

    # --- Unfinished installs (see cubeon/versions.py) ---------------------
    # Delete version folders whose download never finished - a client .jar
    # that never arrived, is truncated, or is not a Minecraft file at all -
    # once, at startup, so they never show up in the Play list. Our installer
    # removes its own partial files when an install FAILS, so what this sweeps
    # is what a hard kill (crash, power cut, full disk) stranded. It is
    # deliberately narrow: a jar that is merely unreadable (locked by a running
    # game, permissions), a folder with broken metadata, or a loader profile
    # missing its base version are all LEFT ALONE - see versions.py for the
    # full list and the mtime grace period protecting a download in flight.
    # Turning it off keeps them for inspection; "Tidy up files" never deletes
    # versions either way.
    "auto_delete_incomplete": True,
}


def _backup_corrupt_config() -> None:
    """Copy a readable-but-broken config.json aside before defaults replace it.

    Keeps at most three `.corrupt-<time>` copies, so repeated launches with a
    broken file cannot fill the home directory.
    """
    if not os.path.exists(CONFIG_PATH):
        return
    dest = f"{CONFIG_PATH}.corrupt-{int(time.time())}"
    try:
        if os.path.exists(dest):
            n = 1
            while os.path.exists(f"{dest}-{n}"):
                n += 1
            dest = f"{dest}-{n}"
        shutil.copy2(CONFIG_PATH, dest)
        backups = sorted(
            (p for p in _sibling_paths(CONFIG_PATH, ".corrupt-")),
            key=lambda p: os.path.getmtime(p))
        for stale in backups[:-3]:
            try:
                os.remove(stale)
            except OSError:
                pass
    except OSError:
        pass  # best-effort: a warning below still tells the user what happened


def _sibling_paths(path: str, marker: str) -> list:
    directory = os.path.dirname(path) or "."
    prefix = os.path.basename(path) + marker
    try:
        return [os.path.join(directory, name)
                for name in os.listdir(directory)
                if name.startswith(prefix)]
    except OSError:
        return []


def load_config() -> dict:
    global _LAST_GOOD_CONFIG
    with _LOAD_LOCK:
        data = None
        status = "missing"
        for attempt in range(3):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    parsed = json.load(f)
            except FileNotFoundError:
                status = "missing"
                break
            except (json.JSONDecodeError, ValueError):
                status = "invalid"
                break
            except OSError:
                status = "unreadable"
                if attempt < 2:
                    time.sleep(0.05)
                    continue
                break
            if isinstance(parsed, dict):
                data = parsed
                status = "ok"
            else:
                status = "invalid"
            break

        if status == "ok":
            cfg = {**DEFAULT_CONFIG, **data}
            # Key migration: max_fps_enabled -> fps_boost_enabled (2026-10-15,
            # the toggle moved from Settings to the Play menu and gained the
            # restore-on-off behaviour). The user's ON/OFF choice carries over.
            if "max_fps_enabled" in data and "fps_boost_enabled" not in data:
                cfg["fps_boost_enabled"] = bool(data["max_fps_enabled"])
            # Custom window frame (2026-10-26 Linux, 2026-10-28 Windows): the
            # branded frame is the default on both. Configs written before that
            # persisted a False the user never CHOSE - it was the shipped
            # default - so flip it ONCE for every supported platform, then
            # honour the toggle for good (the Settings checkbox sets
            # custom_window_chrome_chosen). This is the fix for "Windows 10
            # users aren't getting the custom window decorations": their
            # config.json said false and the policy read that as a decision.
            if ((sys.platform == "win32" or sys.platform.startswith("linux"))
                    and not data.get("custom_window_chrome_chosen")
                    and data.get("custom_window_chrome") is False):
                cfg["custom_window_chrome"] = True
            _LAST_GOOD_CONFIG = dict(cfg)
            return cfg

        if status == "invalid":
            _backup_corrupt_config()
            logging.getLogger(__name__).warning(
                "config.json is not a JSON object; copied it aside as "
                "%s.corrupt-* and starting from defaults", CONFIG_PATH)
        elif status == "unreadable":
            if _LAST_GOOD_CONFIG is not None:
                logging.getLogger(__name__).warning(
                    "config.json could not be read; using the last good "
                    "settings for this session")
                return dict(_LAST_GOOD_CONFIG)
            logging.getLogger(__name__).warning(
                "config.json could not be read; using defaults for this "
                "session (the file was not modified)")

    # Brand-new install (or a config whose JSON is not an object - never a
    # reason to crash startup): seed ram_mb with half of *this machine's* RAM
    # instead of the static 4096 fallback in DEFAULT_CONFIG, so a low-RAM
    # machine doesn't start over-allocated (and a high-RAM one isn't stuck
    # under-using what it has).
    cfg = dict(DEFAULT_CONFIG)
    try:
        # Capped: half of a big machine's RAM is a poor default heap.
        # Minecraft rarely benefits past ~6 GB, and an over-large heap only
        # lengthens GC pauses and starves the rest of the system (combined with
        # a small -Xms it is also no longer committed up front). The slider
        # still goes higher - this is only what a NEW install starts at.
        cfg["ram_mb"] = min(recommended_max_ram_mb(get_system_ram_mb()),
                            DEFAULT_HEAP_CEILING_MB)
    except Exception:
        pass
    return cfg


def launch_java_path() -> "str | None":
    """The Java the launcher will launch with, or None when it lets mll choose.

    launch.build_launch_command hands this to minecraft_launcher_lib as
    executablePath, so when it is set the copy of Java mll installs into the
    game directory can never be the JVM that runs the game - which is what
    lets a version install skip downloading it (see versions.install_version's
    explicit_java). None means do NOT skip: without it mll's own command
    builder falls back to exactly that runtime, and on a machine with no Java
    of its own it is the only Java there is.
    """
    try:
        return (load_config() or {}).get("java_path") or None
    except Exception:
        return None


def save_config(cfg: dict) -> None:
    # Atomic (temp + os.replace): a crash mid-write used to leave a truncated
    # config.json behind, and load_config() then silently reset every setting
    # to defaults. Same guarantee _write_auth_key() gives auth_key.json.
    from .atomicio import write_json
    global _LAST_GOOD_CONFIG
    with _SAVE_LOCK:
        write_json(CONFIG_PATH, cfg)
    with _LOAD_LOCK:
        _LAST_GOOD_CONFIG = dict(cfg)


# ---------------------------------------------------------------------------
# Window geometry persistence
#
# The window's size/position is saved apart from config.json on purpose:
# config.json is rewritten wholesale on every settings change, and geometry
# changes are far more frequent (every move/resize tick would otherwise race
# the config writer). A separate tiny JSON read at startup, appended on
# settle/close, can't corrupt the main config.

GEOMETRY_PATH = os.path.join(CUBEON_HOME, "window_geometry.json")


def load_window_geometry() -> dict:
    """Last-saved {width, height, left, top, maximized}, or {} when absent.

    Values are validated by the caller (clamped to sane defaults) rather than
    here - keep this a dumb read."""
    try:
        with open(GEOMETRY_PATH, "r") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        pass
    return {}


def save_window_geometry(width, height, left, top, maximized) -> None:
    # Validate BEFORE touching the file: a malformed resize event used to
    # truncate the saved geometry (open("w") runs before int() raised). The
    # write itself is atomic, matching the config.json guarantee.
    try:
        record = {
            "width": int(width), "height": int(height),
            "left": int(left) if left is not None else None,
            "top": int(top) if top is not None else None,
            "maximized": bool(maximized),
        }
        if not record["width"] or not record["height"]:
            return
    except (TypeError, ValueError):
        return
    try:
        from .atomicio import write_json
        os.makedirs(CUBEON_HOME, exist_ok=True)
        write_json(GEOMETRY_PATH, record)
    except OSError:
        pass  # a lost geometry save must never break a resize handler


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

# Two threads on a first start must not each mint a different identity before
# either has written the file. The cache is also the session fallback when the
# file exists but cannot be READ (antivirus/sync lock on Windows): refusing to
# overwrite it is the only way to keep the player's uuid.
_AUTH_LOCK = threading.RLock()
_AUTH_CACHE_PATH: "str | None" = None
_AUTH_CACHE_IDENTITY: "dict | None" = None
_AUTH_CACHE_PERSISTED = False

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
    Guaranteed to always return a usable identity: on parse failure it
    regenerates the missing half rather than raising, so callers never have to
    handle "no identity yet". Self-healing - valid halves already on disk are
    preserved; only the missing/invalid field is minted. Legacy files keyed
    {uuid, secret} are migrated to the new names without regenerating either
    value (the uuid MUST survive migration or every server the player has ever
    joined would treat them as a brand-new player).

    A file that exists but cannot be READ is not treated as corrupt: the read
    is retried briefly (Windows antivirus/sync locks) and then the identity
    this process already holds is returned WITHOUT writing the file. A
    damaged file that IS readable is copied to auth_key.json.corrupt-<time>
    before being rewritten.

    Written 0600 (best-effort; a no-op on filesystems that don't support it
    must not break identity creation).
    """
    with _AUTH_LOCK:
        data = {}
        status = "ok"
        for attempt in range(3):
            try:
                with open(AUTH_KEY_PATH, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
            except FileNotFoundError:
                status = "missing"
                break
            except (json.JSONDecodeError, ValueError):
                status = "invalid"
                break
            except OSError:
                if attempt < 2:
                    time.sleep(0.05)
                    continue
                status = "unreadable"
                break
            if isinstance(loaded, dict):
                data = loaded
            else:
                status = "invalid"
            break

        if status == "unreadable":
            # A transient read failure is NOT permission to mint a new
            # identity - that would silently change who the player is (server
            # data, skins, friends). Never overwrite a file we could not read.
            if _AUTH_CACHE_PATH == AUTH_KEY_PATH and _AUTH_CACHE_IDENTITY:
                return dict(_AUTH_CACHE_IDENTITY)
            identity = {"public_uuid": str(uuid.uuid4()),
                        "secret_token": _new_secret()}
            _cache_identity(identity, persisted=False)
            return identity

        if status == "invalid":
            _backup_corrupt_auth_file()
            if _AUTH_CACHE_PATH == AUTH_KEY_PATH and _AUTH_CACHE_IDENTITY:
                # This session already knows the identity; repair the damaged
                # file from it instead of inventing a new account.
                identity = dict(_AUTH_CACHE_IDENTITY)
                _cache_identity(identity, persisted=_write_auth_key(identity))
                return identity

        if (status == "missing"
                and _AUTH_CACHE_PATH == AUTH_KEY_PATH
                and _AUTH_CACHE_IDENTITY and not _AUTH_CACHE_PERSISTED):
            # A write failed earlier in this session, so the identity we minted
            # never reached disk. Keep using it (and retry the write) instead of
            # minting a new one on every call.
            identity = dict(_AUTH_CACHE_IDENTITY)
            _cache_identity(identity, persisted=_write_auth_key(identity))
            return identity

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
        persisted = True
        if dirty or data != identity:
            persisted = _write_auth_key(identity)
        _cache_identity(identity, persisted=persisted)
        return identity


def _cache_identity(identity: dict, *, persisted: bool) -> None:
    """Remember this process's identity (for unreadable-file fallback)."""
    global _AUTH_CACHE_PATH, _AUTH_CACHE_IDENTITY, _AUTH_CACHE_PERSISTED
    _AUTH_CACHE_PATH = AUTH_KEY_PATH
    _AUTH_CACHE_IDENTITY = dict(identity)
    _AUTH_CACHE_PERSISTED = bool(persisted)


def _backup_corrupt_auth_file() -> None:
    """Copy a damaged auth_key.json aside before it is rewritten."""
    if not os.path.exists(AUTH_KEY_PATH):
        return
    dest = f"{AUTH_KEY_PATH}.corrupt-{int(time.time())}"
    try:
        if os.path.exists(dest):
            n = 1
            while os.path.exists(f"{dest}-{n}"):
                n += 1
            dest = f"{dest}-{n}"
        shutil.copy2(AUTH_KEY_PATH, dest)
    except OSError:
        pass  # keeping the old bytes is best-effort; repairing still matters


def _write_auth_key(identity: dict) -> bool:
    """Atomically persist auth_key.json with 0600. Returns False on failure.

    Best-effort: a failed write leaves the previous file intact and is
    non-fatal (the in-memory identity is still returned to the caller for this
    session). The temp name is unique so two writers can never collide.
    """
    directory = os.path.dirname(AUTH_KEY_PATH) or "."
    try:
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".auth-", suffix=".tmp",
                                   dir=directory)
    except OSError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(identity, f, indent=2)
        try:
            os.chmod(tmp, 0o600)  # tighten before the rename, never world-readable
        except OSError:
            pass
        os.replace(tmp, AUTH_KEY_PATH)  # atomic; a crash can't truncate it
        return True
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False


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
    if not isinstance(username, str) or not (3 <= len(username) <= 16):
        return False, "Username must be 3-16 characters"
    if not re.fullmatch(r"[A-Za-z0-9_]+", username):
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


def run_dir_picker(page, dir_picker, on_path=None, **kwargs):
    """Open a Flet FilePicker's FOLDER dialog, delivering the chosen folder
    path (or None on cancel) to on_path - the folder-select sibling of
    run_file_picker, with the same old/new Flet split:

      - Old Flet: get_directory_path() runs synchronously, opens the dialog,
        and later fires dir_picker.on_result. The CALLER wires on_result to
        pull `e.path` and hand it to on_path (a FilePickerResultEvent carries
        the folder in `.path`, unlike files in `.files`).
      - New Flet (0.80+): get_directory_path() is async and returns the path
        directly, so we await it and call on_path ourselves, detaching
        on_result for the duration so it can't also fire and double-report.

    Takes `page`/`dir_picker` untyped so this module stays free of a flet
    import (same reason as run_file_picker).
    """
    result = dir_picker.get_directory_path(**kwargs)
    if inspect.isawaitable(result):
        _prev_on_result = getattr(dir_picker, "on_result", None)
        dir_picker.on_result = None

        async def _await_it():
            try:
                path = await result
                if on_path is not None:
                    on_path(path)
            finally:
                dir_picker.on_result = _prev_on_result

        run_task = getattr(page, "run_task", None)
        if callable(run_task):
            run_task(_await_it)
        else:
            dir_picker.on_result = _prev_on_result
    # Old Flet: the result arrives later via dir_picker.on_result, wired by
    # the caller - nothing further to do here.
